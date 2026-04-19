import os
import json
import logging
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    sheet_names = [s.title for s in spreadsheet.worksheets()]
    if "Gastos" not in sheet_names:
        gastos = spreadsheet.add_worksheet(title="Gastos", rows=1000, cols=6)
        gastos.append_row(["Fecha", "Descripcion", "Monto", "Moneda", "Categoria", "Notas"])
    if "Vencimientos" not in sheet_names:
        venc = spreadsheet.add_worksheet(title="Vencimientos", rows=100, cols=5)
        venc.append_row(["Fecha Vencimiento", "Descripcion", "Monto", "Moneda", "Estado"])
    return spreadsheet

def get_recent_data(spreadsheet):
    try:
        gastos = spreadsheet.worksheet("Gastos").get_all_values()
        vencimientos = spreadsheet.worksheet("Vencimientos").get_all_values()
        recent_gastos = gastos[-20:] if len(gastos) > 1 else [gastos[0]] if gastos else []
        return {"gastos_recientes": recent_gastos, "vencimientos": vencimientos}
    except Exception as e:
        logger.error(f"Error leyendo sheets: {e}")
        return {"gastos_recientes": [], "vencimientos": []}

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")
    try:
        spreadsheet = get_sheet()
        data = get_recent_data(spreadsheet)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system_prompt = f"""Sos un asistente financiero personal amigable que habla en espanol argentino (tuteo con vos).
Tu trabajo es ayudar al usuario a registrar gastos, ingresos y vencimientos.

Fecha y hora actual: {datetime.now().strftime("%d/%m/%Y %H:%M")}

Datos actuales en la planilla:
- Ultimos gastos: {json.dumps(data['gastos_recientes'], ensure_ascii=False)}
- Vencimientos: {json.dumps(data['vencimientos'], ensure_ascii=False)}

Cuando el usuario te diga algo, analiza si es:
1. Un GASTO o INGRESO
2. Un VENCIMIENTO
3. Una CONSULTA

Responde SOLO con JSON valido, sin backticks ni markdown, con esta estructura exacta:
{{"mensaje": "tu respuesta amigable", "accion": "gasto", "datos": {{"fecha": "19/04/2025", "descripcion": "super", "monto": 500, "moneda": "ARS", "categoria": "Comida", "notas": ""}}}}

Los valores posibles de accion son: gasto, vencimiento, consulta, ninguna
Los valores posibles de categoria son: Comida, Transporte, Servicios, Entretenimiento, Salud, Ropa, Ingreso, Otros
Para vencimientos usa fecha_vencimiento en lugar de fecha, y agrega estado: Pendiente"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )

        response_text = response.content[0].text.strip()
        logger.info(f"Claude response: {response_text}")

        if "```" in response_text:
            parts = response_text.split("```")
            response_text = parts[1] if len(parts) > 1 else parts[0]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        parsed = json.loads(response_text.strip())
        mensaje = parsed.get("mensaje", "Entendido!")
        accion = parsed.get("accion", "ninguna")
        datos = parsed.get("datos", {})

        logger.info(f"Accion: {accion}, Datos: {datos}")

        if accion == "gasto" and datos:
            sheet = spreadsheet.worksheet("Gastos")
            sheet.append_row([
                datos.get("fecha", datetime.now().strftime("%d/%m/%Y")),
                datos.get("descripcion", ""),
                datos.get("monto", 0),
                datos.get("moneda", "ARS"),
                datos.get("categoria", "Otros"),
                datos.get("notas", "")
            ])
            logger.info("Gasto guardado en Sheets!")
        elif accion == "vencimiento" and datos:
            sheet = spreadsheet.worksheet("Vencimientos")
            sheet.append_row([
                datos.get("fecha_vencimiento", ""),
                datos.get("descripcion", ""),
                datos.get("monto", 0),
                datos.get("moneda", "ARS"),
                datos.get("estado", "Pendiente")
            ])
            logger.info("Vencimiento guardado en Sheets!")

        await update.message.reply_text(mensaje)

    except json.JSONDecodeError as e:
        logger.error(f"JSON error: {e}")
        await update.message.reply_text("Anotado! Intentá de nuevo si algo no quedó bien.")
    except Exception as e:
        logger.error(f"Error general: {e}")
        await update.message.reply_text("Ups, algo salio mal. Intenta de nuevo.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
