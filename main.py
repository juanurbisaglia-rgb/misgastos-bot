import threading
import asyncio
import os
import json
import logging
from flask import Flask, send_from_directory, Response
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

# ── Flask ──────────────────────────────────────────
flask_app = Flask(__name__)

DASHBOARD_HTML = open(os.path.join(os.path.dirname(__file__), 'dashboard.html')).read()

@flask_app.route('/')
@flask_app.route('/dashboard')
def dashboard():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@flask_app.route('/health')
def health():
    return 'ok'

# ── Google Sheets ──────────────────────────────────
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    sheet_names = [s.title for s in spreadsheet.worksheets()]
    if "Gastos" not in sheet_names:
        g = spreadsheet.add_worksheet(title="Gastos", rows=1000, cols=6)
        g.append_row(["Fecha","Descripcion","Monto","Moneda","Categoria","Notas"])
    if "Vencimientos" not in sheet_names:
        v = spreadsheet.add_worksheet(title="Vencimientos", rows=100, cols=5)
        v.append_row(["Fecha Vencimiento","Descripcion","Monto","Moneda","Estado"])
    return spreadsheet

def get_recent_data(spreadsheet):
    try:
        gastos = spreadsheet.worksheet("Gastos").get_all_values()
        venc = spreadsheet.worksheet("Vencimientos").get_all_values()
        return {"gastos_recientes": gastos[-20:] if len(gastos)>1 else [], "vencimientos": venc}
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return {"gastos_recientes":[], "vencimientos":[]}

# ── Telegram Bot ───────────────────────────────────
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")
    try:
        spreadsheet = get_sheet()
        data = get_recent_data(spreadsheet)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        system_prompt = f"""Sos un asistente financiero personal amigable que habla en espanol argentino.
Fecha: {datetime.now().strftime("%d/%m/%Y %H:%M")}
Ultimos gastos: {json.dumps(data['gastos_recientes'], ensure_ascii=False)}
Vencimientos: {json.dumps(data['vencimientos'], ensure_ascii=False)}
Responde SOLO con JSON valido sin backticks:
{{"mensaje":"respuesta","accion":"gasto|vencimiento|consulta|ninguna","datos":{{"fecha":"DD/MM/YYYY","descripcion":"","monto":0,"moneda":"ARS","categoria":"Comida|Transporte|Servicios|Entretenimiento|Salud|Ropa|Ingreso|Otros","notas":"","fecha_vencimiento":"DD/MM/YYYY","estado":"Pendiente"}}}}"""
        response = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=500, system=system_prompt, messages=[{"role":"user","content":user_message}])
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        parsed = json.loads(text.strip())
        accion = parsed.get("accion","ninguna")
        datos = parsed.get("datos",{})
        if accion == "gasto" and datos:
            spreadsheet.worksheet("Gastos").append_row([datos.get("fecha",datetime.now().strftime("%d/%m/%Y")),datos.get("descripcion",""),datos.get("monto",0),datos.get("moneda","ARS"),datos.get("categoria","Otros"),datos.get("notas","")])
            logger.info("Gasto guardado!")
        elif accion == "vencimiento" and datos:
            spreadsheet.worksheet("Vencimientos").append_row([datos.get("fecha_vencimiento",""),datos.get("descripcion",""),datos.get("monto",0),datos.get("moneda","ARS"),datos.get("estado","Pendiente")])
            logger.info("Vencimiento guardado!")
        await update.message.reply_text(parsed.get("mensaje","Entendido!"))
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Ups, algo salio mal. Intenta de nuevo.")

async def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    logger.info("Bot iniciado!")
    await app.run_polling()

# ── Main ───────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    # Flask en thread separado
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    logger.info(f"Dashboard corriendo en puerto {port}")
    
    # Bot en el loop principal
    asyncio.run(run_bot())
