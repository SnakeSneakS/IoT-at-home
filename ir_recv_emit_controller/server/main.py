import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO
import threading
import serial
import time
from datetime import datetime
from functools import wraps
import dotenv

# =========================
# 設定値
# =========================
dotenv.load_dotenv()
DB_NAME = "ir_remotes.db"  # 今回は使わないけど認証はそのまま
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
PORT = os.getenv("PORT",8080)

SERIAL_PORT = os.getenv("SERIAL_PORT_PATH") 
BAUD_RATE = os.getenv("BAUD_RATE",9600)

CONTROLLER_DIR = "out"  # JSONファイル格納ディレクトリ（フォルダに変更）
os.makedirs(CONTROLLER_DIR, exist_ok=True)
DATA_META_FILENAME = "meta.json"
DATA_SETTING_FILENAME = "setting.json"

# =========================
# Flask & SocketIO 初期化
# =========================
app = Flask(__name__)
app.secret_key = "超秘密のキーにしてください"
socketio = SocketIO(app, async_mode='threading')

# =========================
# シリアルポート接続
# =========================
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
except Exception as e:
    print("Serial port open error:", e)
    ser = None

# =========================
# シリアル受信スレッド
# =========================
def serial_listener():
    global ser
    while True:
        if ser is None:
            time.sleep(30)
            try:
                ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
                print("Serial port reconnected.")
            except Exception as e:
                print("Failed to reopen serial port:", e)
            continue
        try:
            line = ser.readline().decode(errors="ignore").strip()
            if line:
                print("Received serial output from:", line)
                if line.startswith("Received IR Code:"):
                    socketio.emit('ir_signal', {
                        #'time': datetime.now().strftime("%H:%M:%S"),
                        'code': line
                    })
                    #print(line)
                

        except serial.SerialException as e:
            print("Serial error:", e)
            try:
                ser.close()
            except:
                pass
            ser = None
        except Exception as e:
            print("Unexpected error:", e)

listener_thread = threading.Thread(target=serial_listener, daemon=True)
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
        controllers.append({
            "name": foldername,
            "description": description
        })
    return render_template("index.html", controllers=sorted(controllers, key=lambda x: x["name"]))

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
        controllers.append({
            "name": foldername,
            "description": description
        })
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
        data = {
            "name": controller_name,
            "description": "",
            "buttons": []
        }

    try:
        os.makedirs(dir_path, exist_ok=False)  # 新規作成

        meta = {
            "name": data.get("name", controller_name),
            "description": data.get("description", "")
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        setting = {
            "buttons": data.get("buttons", [])
        }
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
                "buttons": setting.get("buttons", [])
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
                "description": data.get("description", "")
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            setting = {
                "buttons": data.get("buttons", [])
            }
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

    if ser is None:
        return jsonify({"status": "error", "message": "シリアルポート未接続"}), 500

    try:
        cmd = f"SEND {code}\n"
        #print(cmd)
        ser.write(cmd.encode())
        print(cmd)
        return jsonify({"status": "ok", "message": f"送信: {code}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# =========================
# メイン実行
# =========================
if __name__ == "__main__":
    socketio.run(app,debug=True)
