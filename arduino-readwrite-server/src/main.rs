use axum::{
    extract::{State, ws::{Message, WebSocket, WebSocketUpgrade}},
    http::{Request, StatusCode},
    middleware::{self, Next},
    response::Response,
    routing::{get, post},
    Json, Router,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serialport::SerialPort;
use std::{
    collections::VecDeque,
    env,
    io::{Read, Write},
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{task, sync::broadcast};
use tracing::{error, info};
//use tracing_subscriber::fmt::writer::MakeWriterExt;
use chrono::Utc;

// ============================
// AppState
// ============================
#[derive(Clone)]
struct AppState {
    serial: Arc<Mutex<Box<dyn SerialPort + Send>>>,
    log_buffer: Arc<Mutex<VecDeque<LogLine>>>, // メモリバッファ
    broadcaster: broadcast::Sender<LogLine>,   // WebSocket配信用
    max_buffer: usize,
}

#[derive(Clone, Serialize)]
struct LogLine {
    timestamp: String,
    line: String,
}

#[derive(Deserialize)]
struct WriteRequest {
    data: String,
}

#[derive(Serialize)]
struct ReadResponse {
    data: String,
}

#[tokio::main]
async fn main() {
    // ===== .env 読み込み =====
    dotenvy::dotenv().ok();

    // ===== 環境変数 =====
    let server_addr =
        env::var("SERVER_ADDR").unwrap_or_else(|_| "0.0.0.0:3000".into());

    let port_name =
        env::var("SERIAL_PORT").expect("SERIAL_PORT must be set");

    let baud_rate: u32 = env::var("SERIAL_BAUDRATE")
        .unwrap_or_else(|_| "9600".into())
        .parse()
        .expect("Invalid SERIAL_BAUDRATE");

    let timeout_ms: u64 = env::var("SERIAL_TIMEOUT_MS")
        .unwrap_or_else(|_| "100".into())
        .parse()
        .expect("Invalid SERIAL_TIMEOUT_MS");

    let log_buffer_size: usize = env::var("LOG_BUFFER_SIZE")
        .unwrap_or_else(|_| "1000".into())
        .parse()
        .expect("Invalid LOG_BUFFER_SIZE");

    // ===== Logging =====
    tracing_subscriber::fmt()
        .with_writer(std::io::stdout)
        .with_ansi(false)
        .init();

    info!("Server starting...");
    info!("Serial Port: {}", port_name);

    // ===== Serial Open =====
    let serial = serialport::new(port_name, baud_rate)
        .timeout(Duration::from_millis(timeout_ms))
        .open()
        .expect("Failed to open serial port");

    // ===== AppState =====
    let (tx, _rx) = broadcast::channel::<LogLine>(1024);
    let state = AppState {
        serial: Arc::new(Mutex::new(serial)),
        log_buffer: Arc::new(Mutex::new(VecDeque::with_capacity(log_buffer_size))),
        broadcaster: tx,
        max_buffer: log_buffer_size,
    };

    // ===== Serial Read Loop =====
    {
        let state = state.clone();
        task::spawn_blocking(move || {
            let mut read_buf = [0u8; 256];
            let mut line_buffer = String::new();

            loop {
                if let Ok(mut port) = state.serial.lock() {
                    if let Ok(n) = port.read(&mut read_buf) {
                        if n > 0 {
                            let chunk = String::from_utf8_lossy(&read_buf[..n]);
                            line_buffer.push_str(&chunk);

                            while let Some(pos) = line_buffer.find('\n') {
                                let line = line_buffer[..pos].trim().to_string();
                                let timestamp = Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();

                                let log_line = LogLine { timestamp: timestamp.clone(), line: line.clone() };

                                // メモリバッファ追加
                                {
                                    let mut buf = state.log_buffer.lock().unwrap();
                                    if buf.len() >= state.max_buffer {
                                        buf.pop_front();
                                    }
                                    buf.push_back(log_line.clone());
                                }

                                // WebSocket配信用
                                let _ = state.broadcaster.send(log_line.clone());

                                // tracing出力
                                info!("[{}] {}", timestamp, line);

                                line_buffer = line_buffer[pos + 1..].to_string();
                            }
                        }
                    }
                }
            }
        });
    }

    // ===== Router =====
    let public_routes = Router::new().route("/", get(root));

    let protected_routes = Router::new()
        .route("/write", post(write_serial))
        .route("/read", get(read_serial))
        .route("/logs", get(get_logs))
        .route("/ws", get(ws_handler)) // ← ここに追加
        .layer(middleware::from_fn(api_key_auth));

    let app = public_routes.merge(protected_routes).with_state(state);

    info!("Server running on http://{}", server_addr);

    let listener = tokio::net::TcpListener::bind(&server_addr)
        .await
        .unwrap();

    axum::serve(listener, app).await.unwrap();
}

// ============================
// Handlers
// ============================

async fn root() -> &'static str {
    "ok"
}

async fn write_serial(
    State(state): State<AppState>,
    Json(req): Json<WriteRequest>,
) -> Result<&'static str, StatusCode> {
    let mut port = state.serial.lock().unwrap();
    port.write_all(req.data.as_bytes())
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    info!("SERIAL_WRITE: {}", req.data.trim());
    Ok("OK")
}

async fn read_serial(
    State(state): State<AppState>,
) -> Json<ReadResponse> {
    let last_line = state.log_buffer.lock().unwrap().back()
        .map(|l| l.line.clone())
        .unwrap_or_default();
    Json(ReadResponse { data: last_line })
}

#[derive(Deserialize)]
struct LogsQuery {
    limit: Option<usize>,
}

async fn get_logs(
    State(state): State<AppState>,
    axum::extract::Query(query): axum::extract::Query<LogsQuery>,
) -> Json<Vec<LogLine>> {
    let limit = query.limit.unwrap_or(50);
    let buf = state.log_buffer.lock().unwrap();
    let logs: Vec<LogLine> = buf.iter().rev().take(limit).cloned().collect();
    Json(logs)
}

// ============================
// API Key Middleware
// ============================
async fn api_key_auth(
    req: Request<axum::body::Body>,
    next: Next,
) -> Result<Response, StatusCode> {
    let api_key = env::var("API_KEY").expect("API_KEY must be set");

    match req.headers().get("x-api-key") {
        Some(value) if value == api_key.as_str() => Ok(next.run(req).await),
        _ => {
            error!("Unauthorized access attempt");
            Err(StatusCode::UNAUTHORIZED)
        }
    }
}


// ============================
// WebSocket
// ============================
async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> impl axum::response::IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, state))
}


// WebSocket ハンドラ
async fn handle_ws(socket: WebSocket, state: AppState) {
    // WebSocket を送信用と受信用に分割
    let (mut sender, mut receiver) = socket.split();

    // broadcast の購読者作成
    let mut rx = state.broadcaster.subscribe();

    // 送信タスク
    let send_task = tokio::spawn(async move {
        while let Ok(log_line) = rx.recv().await {
            let msg_text = serde_json::to_string(&log_line).unwrap_or_default();
            if sender.send(Message::Text(msg_text)).await.is_err() {
                // クライアント切断
                break;
            }
        }
    });

    // 受信タスク
    let receive_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = receiver.next().await {
            if let Message::Text(text) = msg {
                // 受信したテキストをシリアルに書き込む
                if let Ok(mut port) = state.serial.lock() {
                    let _ = port.write_all(text.as_bytes());
                    info!("SERIAL_WRITE_WS: {}", text.trim());
                }
            }
        }
    });

    // 両方のタスクが終了するまで待機
    let _ = tokio::join!(send_task, receive_task);
}
