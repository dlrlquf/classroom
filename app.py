import ipaddress
import os
import secrets
import sys
import threading
import webbrowser

from flask import Flask

from database import init_app as init_database
from extensions import socketio
from routes import bp
import events  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import landgrab  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import lobby  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import mindgame  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import responses  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import seating  # noqa: F401  (소켓 이벤트 핸들러 등록용)
import truefalse  # noqa: F401  (소켓 이벤트 핸들러 등록용)

PORT = 5000

# PyInstaller 실행 파일은 임시 폴더에서 풀리므로 DB와 비밀키는 실행 파일 옆에 둔다.
if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
    # 콘솔 없는 빌드(--noconsole)에서는 stdout/stderr가 없으므로 로그 파일로 대신한다.
    if sys.stdout is None or sys.stderr is None:
        os.makedirs(os.path.join(base_dir, "instance"), exist_ok=True)
        log_file = open(
            os.path.join(base_dir, "instance", "server.log"),
            "a",
            encoding="utf-8",
            buffering=1,
        )
        sys.stdout = sys.stdout or log_file
        sys.stderr = sys.stderr or log_file
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, instance_path=os.path.join(base_dir, "instance"))
os.makedirs(app.instance_path, exist_ok=True)

secret_key = os.environ.get("FLASK_SECRET_KEY")
if not secret_key:
    secret_key_path = os.path.join(app.instance_path, "secret_key")
    try:
        with open(secret_key_path, "x", encoding="utf-8") as key_file:
            key_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    with open(secret_key_path, encoding="utf-8") as key_file:
        secret_key = key_file.read()

app.config["SECRET_KEY"] = secret_key
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["ADMIN_ALLOWED_IPS"] = {
    ipaddress.ip_address(address.strip())
    for address in os.environ.get(
        "ADMIN_ALLOWED_IPS", "127.0.0.1,::1"
    ).split(",")
    if address.strip()
}
app.register_blueprint(bp)
app.register_blueprint(landgrab.bp)
init_database(app)
socketio.init_app(app)

    
if __name__ == '__main__':
    threading.Timer(
        1.0, webbrowser.open, args=(f"http://127.0.0.1:{PORT}/",)
    ).start()
    socketio.run(app, host='0.0.0.0', port=PORT)