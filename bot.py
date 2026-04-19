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
        return {"gastos_recientes": gastos[-50:] if len(gastos)>1 else [], "vencimientos": venc}
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return {"gastos_recientes":[], "vencimientos":[]}

def get_mes_actual(spreadsheet):
    try:
        gastos = spreadsheet.worksheet("Gastos").get_all_values()
        if len(gastos) <= 1:
            return []
        mes_actual = datetime.now().strftime("%m/%Y")
        return [g for g in gastos[1:] if len(g) > 0 and g[0].endswith(mes_actual)]
    except:
        return []

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")
    try:
        spreadsheet = get_sheet()
        data = get_recent_data(spreadsheet)
        gastos_mes = get_mes_actual(spreadsheet)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system_prompt = f"""Sos un asistente financiero personal amigable que habla en espanol argentino (tuteo con vos).
Fecha: {datetime.now().strftime("%d/%m/%Y %H:%M")}

DATOS ACTUALES:
Gastos del mes actual: {json.dumps(gastos_mes, ensure_ascii=False)}
Ultimos gastos (hasta 50): {json.dumps(data['gastos_recientes'], ensure_ascii=False)}
Vencimientos: {json.dumps(data['vencimientos'], ensure_ascii=False)}

GASTOS FIJOS MENSUALES CONOCIDOS:
- Monotributo: $81.542 (dia 18)
- Starlink: $63.000 (dia 20)
- Microsoft: $4.885 (dia 12)
- Claude: USD 20 (dia 15)
- iCloud: USD 3.8 (dia 29)
- Sueldo: $2.138.000 (principios de mes)

Cuando el usuario pida un RESUMEN o consulta sobre sus finanzas, analiza los datos y responde con un resumen claro que incluya:
- Total gastado en el mes
- Desglose por categoria
- Gastos para Agritest si hay
- Proximos vencimientos importantes
- Saldo estimado del mes

Para registrar gastos o vencimientos, responde SOLO con JSON valido sin backticks:
{{"mensaje":"respuesta amigable","accion":"gasto|vencimiento|consulta|ninguna","datos":{{"fecha":"DD/MM/YYYY","descripcion":"","monto":0,"moneda":"ARS","categoria":"Comida|Transporte|Servicios|Entretenimiento|Salud|Ropa|Ingreso|Agritest|Otros","notas":"","fecha_vencimiento":"DD/MM/YYYY","estado":"Pendiente"}}}}

Para consultas y resumenes, responde directamente en texto natural sin JSON.
Usa emojis para que sea mas facil de leer."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )

        text = response.content[0].text.strip()
        logger.info(f"Claude response: {text[:200]}")

        # Intentar parsear como JSON, si falla es texto directo
        try:
            if '{' in text:
    text = text[text.index('{'):text.rindex('}')+1]
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"): text = text[4:]
                parsed = json.loads(text.strip())
                accion = parsed.get("accion","ninguna")
                datos = parsed.get("datos",{})
                mensaje = parsed.get("mensaje","Entendido!")

                if accion == "gasto" and datos:
                    spreadsheet.worksheet("Gastos").append_row([
                        datos.get("fecha", datetime.now().strftime("%d/%m/%Y")),
                        datos.get("descripcion",""),
                        datos.get("monto",0),
                        datos.get("moneda","ARS"),
                        datos.get("categoria","Otros"),
                        datos.get("notas","")
                    ])
                    logger.info("Gasto guardado!")
                elif accion == "vencimiento" and datos:
                    spreadsheet.worksheet("Vencimientos").append_row([
                        datos.get("fecha_vencimiento",""),
                        datos.get("descripcion",""),
                        datos.get("monto",0),
                        datos.get("moneda","ARS"),
                        datos.get("estado","Pendiente")
                    ])
                    logger.info("Vencimiento guardado!")

                await update.message.reply_text(mensaje)
            else:
                # Respuesta de texto directo (resumen, consulta)
                await update.message.reply_text(text)

        except json.JSONDecodeError:
            await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Ups, algo salio mal. Intenta de nuevo.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
