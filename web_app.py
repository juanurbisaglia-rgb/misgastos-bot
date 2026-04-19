import os
import threading
from flask import Flask, Response

flask_app = Flask(__name__)

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')) as f:
    DASHBOARD_HTML = f.read()

@flask_app.route('/')
@flask_app.route('/dashboard')
def dashboard():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@flask_app.route('/health')
def health():
    return 'ok'

def start_bot():
    import subprocess
    subprocess.Popen(['python', 'bot.py'])

# Arranca el bot cuando gunicorn carga la app
threading.Thread(target=start_bot, daemon=True).start()
