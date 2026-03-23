import json
import os
import threading
from functools import wraps

import dotenv
import websocket
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO


def must_get_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return value


# =========================
# 設定値
# =========================
dotenv.load_dotenv()
# DB_NAME = "ir_remotes.db"  # 今回は使わない
USERNAME = must_get_env("APP_USERNAME")
PASSWORD = must_get_env("APP_PASSWORD")
PORT = os.getenv("PORT", 8080)
HOST = os.getenv("HOST", "0.0.0.0")
ARDUINO_READWRITE_WS_API_KEY = must_get_env("ARDUINO_READWRITE_WS_API_KEY")
ARDUINO_READWRITE_WS_URL = os.getenv(
    "ARDUINO_READWRITE_WS_URL", "ws://127.0.0.1:3000/ws"
)


CONTROLLER_DIR = "out"  # JSONファイル格納ディレクトリ（フォルダに変更）
os.makedirs(CONTROLLER_DIR, exist_ok=True)
DATA_META_FILENAME = "meta.json"
DATA_SETTING_FILENAME = "setting.json"

# =========================
# Flask & SocketIO 初期化
# =========================
app = Flask(__name__)
app.secret_key = "超秘密のキーにしてください"
socketio = SocketIO(app, async_mode="threading")


# =========================
# Websocketスレッド
# =========================
ws_client = None


def ws_listener():
    global ws_client

    def on_message(ws, message):
        # WebSockettサーバーからのログを Flask SocketIO に送信
        try:
            log = json.loads(message)
            socketio.emit("ir_signal", {"code": log["line"]})
        except Exception as e:
            print("Failed to parse WS message:", e)

    def on_error(ws, error):
        print("WebSocket error:", error)
        os._exit(1)

    def on_close(ws, close_status_code, close_msg):
        print("WebSocket closed:", close_status_code, close_msg)
        os._exit(1)

    def on_open(ws):
        print("Connected to Rust WS server")

    headers = [f"x-api-key: {ARDUINO_READWRITE_WS_API_KEY}"]

    ws_client = websocket.WebSocketApp(
        ARDUINO_READWRITE_WS_URL,
        header=headers,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws_client.run_forever()


try:
    ws_test = websocket.create_connection(
        ARDUINO_READWRITE_WS_URL,
        header=[f"x-api-key: {ARDUINO_READWRITE_WS_API_KEY}"],
        timeout=5,  # 接続タイムアウト
    )
    ws_test.close()
except Exception as e:
    raise RuntimeError(f"Rust WS サーバーに接続できません: {e}")


# バックグラウンドで WS 接続開始
listener_thread = threading.Thread(target=ws_listener, daemon=True)
listener_thread.start()


# =========================
# 認証機能
# =========================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            flash("ログインしてください")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# =========================
# ファイル・フォルダ名チェック
# =========================
def safe_foldername(foldername):
    # フォルダ名として使う文字列の簡易チェック（英数字と-_のみ許可など）
    import re

    return bool(re.match(r"^[a-zA-Z0-9_-]+$", foldername))


def get_controller_dir(name):
    # コントローラ名（拡張子なし）からディレクトリパスを返す
    return os.path.join(CONTROLLER_DIR, name)


# =========================
# ルーティング
# =========================


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # print("hoge",username,password,USERNAME,PASSWORD)
        if username == USERNAME and password == PASSWORD:
            session["logged_in"] = True
            flash("ログイン成功しました")
            return redirect(url_for("index"))
        else:
            flash("ユーザー名かパスワードが間違っています")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました")
    return redirect(url_for("login"))


@app.route("/health", methods=["GET"])
def health():
    """
    ヘルスチェック用エンドポイント
    """
    return jsonify(
        {
            "status": "ok",
            "ws_connected": ws_client and ws_client.sock and ws_client.sock.connected,
        }
    )


@app.route("/")
@login_required
def index():
    # コントローラディレクトリ内のサブフォルダ一覧を取得し、meta.jsonを読み込む
    controllers = []
    for foldername in os.listdir(CONTROLLER_DIR):
        folderpath = os.path.join(CONTROLLER_DIR, foldername)
        if not os.path.isdir(folderpath):
            continue
        if not safe_foldername(foldername):
            continue
        meta_path = os.path.join(folderpath, DATA_META_FILENAME)
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                description = meta.get("description", "")
            except Exception:
                description = "(読み込みエラー)"
        else:
            description = "(メタ情報なし)"
        controllers.append({"name": foldername, "description": description})
    return render_template(
        "index.html", controllers=sorted(controllers, key=lambda x: x["name"])
    )


@app.route("/controller/<controller_name>")
@login_required
def controller_editor(controller_name):
    if not safe_foldername(controller_name):
        flash("不正なフォルダ名です")
        return redirect(url_for("index"))
    dir_path = get_controller_dir(controller_name)
    if not os.path.exists(dir_path):
        flash("指定されたコントローラデータが見つかりません")
        return redirect(url_for("index"))
    return render_template("controller.html", controller_name=controller_name)


# ①コントローラ一覧API
@app.route("/api/controllers", methods=["GET"])
@login_required
def api_list_controllers():
    controllers = []
    for foldername in os.listdir(CONTROLLER_DIR):
        folderpath = os.path.join(CONTROLLER_DIR, foldername)
        if not os.path.isdir(folderpath):
            continue
        if not safe_foldername(foldername):
            continue
        meta_path = os.path.join(folderpath, DATA_META_FILENAME)
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                description = meta.get("description", "")
            except Exception:
                description = "(読み込みエラー)"
        else:
            description = "(メタ情報なし)"
        controllers.append({"name": foldername, "description": description})
    return jsonify({"controllers": controllers})


# ②コントローラ新規作成API
@app.route("/api/controllers/<controller_name>", methods=["POST"])
@login_required
def api_create_controller(controller_name):
    if not safe_foldername(controller_name):
        return jsonify({"error": "不正なフォルダ名です"}), 400

    dir_path = get_controller_dir(controller_name)
    meta_path = os.path.join(dir_path, DATA_META_FILENAME)
    setting_path = os.path.join(dir_path, DATA_SETTING_FILENAME)

    if os.path.exists(dir_path):
        # ディレクトリが存在したら重複
        return jsonify({"error": "コントローラは既に存在します"}), 409

    data = request.get_json()
    if not data:
        data = {"name": controller_name, "description": "", "buttons": []}

    try:
        os.makedirs(dir_path, exist_ok=False)  # 新規作成

        meta = {
            "name": data.get("name", controller_name),
            "description": data.get("description", ""),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        setting = {"buttons": data.get("buttons", [])}
        with open(setting_path, "w", encoding="utf-8") as f:
            json.dump(setting, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "created"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ③コントローラ読み書きAPI (GET/POST)
@app.route("/api/controller/<controller_name>", methods=["GET", "POST"])
@login_required
def api_controller(controller_name):
    if not safe_foldername(controller_name):
        return jsonify({"error": "不正なフォルダ名です"}), 400

    dir_path = get_controller_dir(controller_name)
    meta_path = os.path.join(dir_path, DATA_META_FILENAME)
    setting_path = os.path.join(dir_path, DATA_SETTING_FILENAME)

    if request.method == "GET":
        if not os.path.exists(meta_path) or not os.path.exists(setting_path):
            return jsonify({"error": "not found"}), 404
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            with open(setting_path, "r", encoding="utf-8") as f:
                setting = json.load(f)

            data = {
                "name": meta.get("name", controller_name),
                "description": meta.get("description", ""),
                "buttons": setting.get("buttons", []),
            }
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    else:  # POST (保存)
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400

        try:
            meta = {
                "name": data.get("name", controller_name),
                "description": data.get("description", ""),
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            setting = {"buttons": data.get("buttons", [])}
            with open(setting_path, "w", encoding="utf-8") as f:
                json.dump(setting, f, ensure_ascii=False, indent=2)

            return jsonify({"status": "saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


# ④コントローラ削除API
@app.route("/api/controllers/<controller_name>", methods=["DELETE"])
@login_required
def api_delete_controller(controller_name):
    import shutil

    if not safe_foldername(controller_name):
        return jsonify({"error": "不正なフォルダ名です"}), 400
    dir_path = get_controller_dir(controller_name)
    if not os.path.exists(dir_path):
        return jsonify({"error": "ファイルが存在しません"}), 404
    try:
        shutil.rmtree(dir_path)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# send_ir は既存のまま
@app.route("/send_ir", methods=["POST"])
@login_required
def send_ir():
    data = request.get_json()
    code = data.get("code")
    if not code:
        return jsonify({"status": "error", "message": "コード指定なし"}), 400

    try:
        if ws_client and ws_client.sock and ws_client.sock.connected:
            cmd = f"SEND_IR {code}\n"
            ws_client.send(cmd)
            print("Sent to Rust WS:", cmd)
            return jsonify({"status": "ok", "message": f"送信: {code}"})
        else:
            return jsonify({"status": "error", "message": "Rust WS 未接続"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =========================
# メイン実行
# =========================
if __name__ == "__main__":
    socketio.run(app, host=HOST, port=PORT, debug=True)
