import os
import json
import threading
from flask import Flask, Response, jsonify
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

flask_app = Flask(__name__)

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')) as f:
    DASHBOARD_HTML = f.read()

def get_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.environ["SPREADSHEET_ID"])

@flask_app.route('/')
@flask_app.route('/dashboard')
def dashboard():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@flask_app.route('/api/datos')
def datos():
    try:
        spreadsheet = get_sheet()
        mes_actual = datetime.now().strftime("%m/%Y")

        # Gastos
        gastos_raw = spreadsheet.worksheet("Gastos").get_all_values()
        headers_g = gastos_raw[0] if gastos_raw else []
        gastos = [dict(zip(headers_g, row)) for row in gastos_raw[1:]] if len(gastos_raw) > 1 else []

        # Gastos del mes actual
        gastos_mes = [g for g in gastos if g.get("Fecha","").endswith(mes_actual)]

        # Total por categoria del mes
        categorias = {}
        agritest_total = 0
        for g in gastos_mes:
            cat = g.get("Categoría", g.get("Categoria", "Otros"))
            try:
                monto = float(str(g.get("Monto",0)).replace(",","."))
            except:
                monto = 0
            if cat == "Agritest":
                agritest_total += monto
            else:
                categorias[cat] = categorias.get(cat, 0) + monto

        total_mes = sum(categorias.values()) + agritest_total

        # Vencimientos
        venc_raw = spreadsheet.worksheet("Vencimientos").get_all_values()
        headers_v = venc_raw[0] if venc_raw else []
        vencimientos = [dict(zip(headers_v, row)) for row in venc_raw[1:]] if len(venc_raw) > 1 else []

        # Gastos Agritest del mes
        gastos_agritest = [g for g in gastos_mes if g.get("Categoria") == "Agritest"]

        return jsonify({
            "ok": True,
            "mes": datetime.now().strftime("%B %Y"),
            "total_gastos_mes": round(total_mes, 2),
            "agritest_total": round(agritest_total, 2),
            "gastos_agritest": gastos_agritest,
            "categorias": {k: round(v, 2) for k, v in categorias.items()},
            "gastos_mes": gastos_mes,
            "vencimientos": vencimientos,
            "ultimo_update": (datetime.utcnow().replace(hour=(datetime.utcnow().hour - 3) % 24)).strftime("%d/%m/%Y %H:%M")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@flask_app.route('/health')
def health():
    return 'ok'

def start_bot():
    import subprocess
    subprocess.Popen(['python', 'bot.py'])

threading.Thread(target=start_bot, daemon=True).start()
