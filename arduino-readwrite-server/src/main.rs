use axum::{
    Json, Router,
    extract::{
        State,
        ws::{Message, WebSocket, WebSocketUpgrade},
    },
    http::{Request, StatusCode},
    middleware::{self, Next},
    response::Response,
    routing::{get, post},
};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env,
    io::{ErrorKind, Read, Write},
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    sync::{broadcast, mpsc},
    task,
};
use tracing::{error, info};

// ============================
// AppState
// ============================
#[derive(Clone)]
struct AppState {
    serial_tx: mpsc::Sender<String>, // ← 書き込み用
    log_buffer: Arc<Mutex<VecDeque<LogLine>>>,
    broadcaster: broadcast::Sender<LogLine>,
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
    dotenvy::dotenv().ok();

    let server_addr = env::var("SERVER_ADDR").unwrap_or_else(|_| "0.0.0.0:3000".into());

    let port_name = env::var("SERIAL_PORT").expect("SERIAL_PORT must be set");

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

    tracing_subscriber::fmt()
        .with_writer(std::io::stdout)
        .with_ansi(false)
        .init();

    info!("Server starting...");

    // =========================
    // Channel作成
    // =========================
    let (write_tx, mut write_rx) = mpsc::channel::<String>(100);
    let (broadcast_tx, _) = broadcast::channel::<LogLine>(1024);

    let state = AppState {
        serial_tx: write_tx.clone(),
        log_buffer: Arc::new(Mutex::new(VecDeque::with_capacity(log_buffer_size))),
        broadcaster: broadcast_tx.clone(),
        max_buffer: log_buffer_size,
    };

    // =========================
    // Serial専用スレッド
    // =========================
    {
        let port_name = port_name.clone();
        let state_clone = state.clone();

        task::spawn_blocking(move || {
            let mut port = serialport::new(port_name, baud_rate)
                .timeout(Duration::from_millis(timeout_ms))
                .open()
                .expect("Failed to open serial port");

            let mut read_buf = [0u8; 256];
            let mut line_buffer = String::new();

            loop {
                // =====================
                // 1️⃣ Write優先処理
                // =====================
                while let Ok(data) = write_rx.try_recv() {
                    if let Err(e) = port.write_all(data.as_bytes()) {
                        error!("Serial write error: {:?}", e);
                        std::process::exit(1);
                    }
                }

                // =====================
                // 2️⃣ Read処理
                // =====================
                match port.read(&mut read_buf) {
                    Ok(n) if n > 0 => {
                        let chunk = String::from_utf8_lossy(&read_buf[..n]);
                        line_buffer.push_str(&chunk);

                        while let Some(pos) = line_buffer.find('\n') {
                            let line = line_buffer[..pos].trim().to_string();

                            let timestamp = Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();

                            let log_line = LogLine {
                                timestamp: timestamp.clone(),
                                line: line.clone(),
                            };

                            // バッファ保存
                            {
                                let mut buf = state_clone.log_buffer.lock().unwrap();

                                if buf.len() >= state_clone.max_buffer {
                                    buf.pop_front();
                                }

                                buf.push_back(log_line.clone());
                            }

                            let _ = state_clone.broadcaster.send(log_line.clone());

                            info!("[{}] READ SERIAL: {}", timestamp, line);

                            line_buffer = line_buffer[pos + 1..].to_string();
                        }
                    }
                    Ok(_) => {}

                    // 👇 ここがポイント（タイムアウト無視）
                    Err(ref e) if e.kind() == ErrorKind::TimedOut => {
                        // 何もしない（ログも出さないのが普通）
                    }

                    // 👇 それ以外は異常として扱う
                    Err(e) => {
                        error!("Serial read error: {:?}", e);
                        std::process::exit(1);
                    }
                }
            }
        });
    }

    // =========================
    // Router
    // =========================
    let public_routes = Router::new().route("/", get(root));

    let protected_routes = Router::new()
        .route("/write", post(write_serial))
        .route("/read", get(read_serial))
        .route("/logs", get(get_logs))
        .route("/ws", get(ws_handler))
        .layer(middleware::from_fn(api_key_auth));

    let app = public_routes.merge(protected_routes).with_state(state);

    let listener = tokio::net::TcpListener::bind(&server_addr).await.unwrap();

    info!("Server running on http://{}", server_addr);

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
    let line = format!("{}\n", req.data.trim());

    state
        .serial_tx
        .send(line)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    Ok("OK")
}

async fn read_serial(State(state): State<AppState>) -> Json<ReadResponse> {
    let last_line = state
        .log_buffer
        .lock()
        .unwrap()
        .back()
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
async fn api_key_auth(req: Request<axum::body::Body>, next: Next) -> Result<Response, StatusCode> {
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

async fn handle_ws(socket: WebSocket, state: AppState) {
    let (mut sender, mut receiver) = socket.split();

    let mut rx = state.broadcaster.subscribe();
    let serial_tx = state.serial_tx.clone();

    // 送信タスク
    let send_task = tokio::spawn(async move {
        while let Ok(log_line) = rx.recv().await {
            let msg_text = serde_json::to_string(&log_line).unwrap_or_default();

            if sender.send(Message::Text(msg_text)).await.is_err() {
                break;
            }
        }
    });

    // 受信タスク
    let receive_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = receiver.next().await {
            if let Message::Text(text) = msg {
                let _ = serial_tx.send(text).await;
            }
        }
    });

    let _ = tokio::join!(send_task, receive_task);
}
