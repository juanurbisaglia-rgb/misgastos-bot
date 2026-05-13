import os
import re
import json
import threading
import requests as req
from flask import Flask, Response, jsonify, request, session, redirect, render_template_string
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime, timedelta
from functools import wraps

flask_app = Flask(__name__)
flask_app.secret_key = os.environ["SECRET_KEY"]
flask_app.permanent_session_lifetime = timedelta(days=30)

_dolar_cache = {"valor": 1390, "fecha": ""}

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')) as f:
    DASHBOARD_HTML = f.read()

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'preview.html')) as f:
    PREVIEW_HTML = f.read()

LOGIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mis Finanzas</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0f1117;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    .card {
      background: #1a1d27;
      border: 1px solid #2a2d3a;
      border-radius: 16px;
      padding: 40px 36px;
      width: 100%;
      max-width: 360px;
    }
    h1 {
      color: #f0f2f8;
      font-size: 20px;
      font-weight: 600;
      margin-bottom: 6px;
    }
    .sub {
      color: #6b7280;
      font-size: 13px;
      margin-bottom: 28px;
    }
    label {
      display: block;
      color: #9ca3af;
      font-size: 12px;
      font-weight: 500;
      margin-bottom: 6px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    input[type=password] {
      width: 100%;
      background: #0f1117;
      border: 1px solid #2a2d3a;
      border-radius: 8px;
      color: #f0f2f8;
      font-size: 15px;
      padding: 11px 14px;
      outline: none;
      transition: border-color 0.15s;
    }
    input[type=password]:focus { border-color: #6366f1; }
    .error {
      background: #2d1f1f;
      border: 1px solid #7f1d1d;
      border-radius: 8px;
      color: #fca5a5;
      font-size: 13px;
      padding: 10px 14px;
      margin-bottom: 18px;
    }
    button {
      width: 100%;
      margin-top: 16px;
      background: #6366f1;
      border: none;
      border-radius: 8px;
      color: #fff;
      font-size: 15px;
      font-weight: 600;
      padding: 12px;
      cursor: pointer;
      transition: background 0.15s;
    }
    button:hover { background: #4f46e5; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Mis Finanzas</h1>
    <p class="sub">Ingresá tu contraseña para continuar</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
      <label for="password">Contraseña</label>
      <input type="password" id="password" name="password" autofocus autocomplete="current-password">
      <button type="submit">Entrar</button>
    </form>
  </div>
</body>
</html>"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


MES_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

def parse_tc_installments(gastos, ahora):
    result = []
    for g in gastos:
        if g.get("Categoria","") != "Tarjeta Credito":
            continue
        notas = g.get("Notas","")
        fecha_str = g.get("Fecha","")
        try:
            n = int(re.search(r'(\d+)\s*cuotas?', notas, re.IGNORECASE).group(1)) if re.search(r'(\d+)\s*cuotas?', notas, re.IGNORECASE) else 1
            venc_d = int(re.search(r'Venc:\s*(\d{1,2})', notas).group(1)) if re.search(r'Venc:\s*(\d{1,2})', notas) else 22
            cierre_d = int(re.search(r'Cierre:\s*(\d{1,2})', notas).group(1)) if re.search(r'Cierre:\s*(\d{1,2})', notas) else 15
            monto = float(str(g.get("Monto",0)).replace(",","."))
            cuota_amt = round(monto / n, 2)
            parts = fecha_str.split("/")
            if len(parts) != 3:
                continue
            p_day, p_month, p_year = int(parts[0]), int(parts[1]), int(parts[2])
            fm, fy = (p_month, p_year) if p_day <= cierre_d else (p_month + 1, p_year)
            if fm > 12:
                fm, fy = 1, fy + 1
            for i in range(n):
                m, y = fm + i, fy
                while m > 12:
                    m -= 12
                    y += 1
                vd = min(venc_d, 28)
                try:
                    due = datetime(y, m, vd)
                except:
                    due = datetime(y, m, 1)
                result.append({
                    "descripcion": g.get("Descripcion","Compra TC"),
                    "fecha_compra": fecha_str,
                    "cuota": i+1,
                    "total_cuotas": n,
                    "monto": cuota_amt,
                    "vencimiento": f"{str(vd).zfill(2)}/{str(m).zfill(2)}/{y}",
                    "mes_label": MES_NAMES[m-1],
                    "pagada": due.date() < ahora.date(),
                    "mes_actual": (m == ahora.month and y == ahora.year)
                })
        except:
            continue
    return result


def get_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.environ["SPREADSHEET_ID"])

def get_dolar_bna():
    global _dolar_cache
    try:
        r = req.get("https://dolarapi.com/v1/dolares/oficial", timeout=5)
        data = r.json()
        _dolar_cache["valor"] = data.get("venta", 1390)
        _dolar_cache["fecha"] = data.get("fechaActualizacion", "")[:10]
    except:
        pass
    return _dolar_cache


@flask_app.route('/preview')
def preview():
    return Response(PREVIEW_HTML, mimetype='text/html')


@flask_app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == os.environ.get('DASHBOARD_PASSWORD', ''):
            session.permanent = True
            session['logged_in'] = True
            return redirect('/dashboard')
        error = 'Contraseña incorrecta'
    return render_template_string(LOGIN_HTML, error=error)


@flask_app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@flask_app.route('/api/dolar')
@login_required
def dolar():
    return jsonify(get_dolar_bna())

@flask_app.route('/')
@flask_app.route('/dashboard')
@login_required
def dashboard():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@flask_app.route('/api/datos')
@login_required
def datos():
    try:
        spreadsheet = get_sheet()
        mes_actual = request.args.get('mes', datetime.now().strftime("%m/%Y"))

        # Gastos
        gastos_raw = spreadsheet.worksheet("Gastos").get_all_values()
        headers_g = gastos_raw[0] if gastos_raw else []
        gastos = [dict(zip(headers_g, row)) for row in gastos_raw[1:]] if len(gastos_raw) > 1 else []

        # Gastos personales del mes seleccionado (excluye Agritest)
        gastos_mes = [g for g in gastos if g.get("Fecha","").endswith(mes_actual) and g.get("Cliente","") != "Agritest"]

        # Total por categoria del mes (solo personales)
        categorias = {}
        for g in gastos_mes:
            cat = g.get("Categoria","Otros")
            try:
                monto = float(str(g.get("Monto",0)).replace(",","."))
            except:
                monto = 0
            categorias[cat] = categorias.get(cat, 0) + monto

        total_mes = sum(categorias.values())

        # Agritest: todos los pendientes sin importar el mes (para el total a cobrar)
        gastos_agritest = [g for g in gastos if g.get("Cliente","") == "Agritest" and g.get("Estado","pendiente").lower() in ("pendiente","")]
        # Agritest: solo del mes seleccionado (para la lista inferior)
        gastos_agritest_mes = [g for g in gastos if g.get("Fecha","").endswith(mes_actual) and g.get("Cliente","") == "Agritest"]
        agritest_total = 0
        for g in gastos_agritest:
            try:
                agritest_total += float(str(g.get("Monto",0)).replace(",","."))
            except:
                pass

        # Vencimientos
        venc_raw = spreadsheet.worksheet("Vencimientos").get_all_values()
        headers_v = venc_raw[0] if venc_raw else []
        vencimientos = [dict(zip(headers_v, row)) for row in venc_raw[1:]] if len(venc_raw) > 1 else []

        # Promedio de gastos personales de meses anteriores (para proyección de ahorro)
        monthly_personal = {}
        for g in gastos:
            fecha = g.get("Fecha","")
            if not fecha or g.get("Cliente","") == "Agritest":
                continue
            parts = fecha.split("/")
            if len(parts) == 3:
                mes_key = f"{parts[1]}/{parts[2]}"
                if mes_key == mes_actual:
                    continue  # mes actual incompleto, no contar
                cat = g.get("Categoria","")
                if cat == "Ingreso":
                    continue
                try:
                    monto = float(str(g.get("Monto",0)).replace(",","."))
                    monthly_personal[mes_key] = monthly_personal.get(mes_key, 0) + monto
                except:
                    pass
        gasto_promedio_mensual = round(sum(monthly_personal.values()) / len(monthly_personal)) if monthly_personal else 0

        ahora = datetime.now()
        tc_cuotas = parse_tc_installments(gastos, ahora)
        tc_total_mes = sum(c["monto"] for c in tc_cuotas if c.get("mes_actual") and not c.get("pagada"))

        return jsonify({
            "ok": True,
            "mes": datetime.now().strftime("%B %Y"),
            "total_gastos_mes": round(total_mes, 2),
            "agritest_total": round(agritest_total, 2),
            "gastos_agritest": gastos_agritest,
            "gastos_agritest_mes": gastos_agritest_mes,
            "categorias": {k: round(v, 2) for k, v in categorias.items()},
            "gastos_mes": gastos_mes,
            "vencimientos": vencimientos,
            "gasto_promedio_mensual": gasto_promedio_mensual,
            "tc_cuotas": [c for c in tc_cuotas if not c["pagada"]],
            "tc_total_mes": round(tc_total_mes, 2),
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
