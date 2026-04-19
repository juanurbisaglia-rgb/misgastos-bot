import os
from flask import Flask, Response

flask_app = Flask(__name__)

DASHBOARD_HTML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')).read()

@flask_app.route('/')
@flask_app.route('/dashboard')
def dashboard():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@flask_app.route('/health')
def health():
    return 'ok'
