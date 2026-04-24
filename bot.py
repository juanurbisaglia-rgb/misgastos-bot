import os
import json
import logging
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARG_TZ = ZoneInfo('America/Argentina/Buenos_Aires')
CHAT_ID_FILE = '/tmp/chat_id.txt'

GASTOS_FIJOS_NOTIF = [
    {"nombre": "Microsoft",    "dia": 12, "monto": "$4.885",   "plataforma": "Mercado Pago"},
    {"nombre": "Claude",       "dia": 15, "monto": "USD 20",   "plataforma": "Cocos Capital"},
    {"nombre": "Monotributo",  "dia": 18, "monto": "$81.542",  "plataforma": "Mercado Pago"},
    {"nombre": "Starlink",     "dia": 20, "monto": "$63.000",  "plataforma": "Mercado Pago"},
    {"nombre": "Tarjeta BNA",  "dia": 20, "monto": "≈$24.289", "plataforma": "BNA Home Banking"},
    {"nombre": "iCloud",       "dia": 29, "monto": "USD 3.8",  "plataforma": "Mercado Pago"},
]

def save_chat_id(chat_id):
    try:
        with open(CHAT_ID_FILE, 'w') as f:
            f.write(str(chat_id))
    except:
        pass

def load_chat_id():
    try:
        with open(CHAT_ID_FILE) as f:
            return int(f.read().strip())
    except:
        return None

async def daily_reminder(context):
    chat_id = load_chat_id()
    if not chat_id:
        return
    manana = datetime.now(ARG_TZ) + timedelta(days=1)
    dia = manana.day
    mes = manana.month
    vencen = [g for g in GASTOS_FIJOS_NOTIF if g["dia"] == dia]
    if mes == 8 and dia == 29:
        vencen.append({"nombre": "Google Drive", "monto": "USD 20", "plataforma": "Cocos Capital (anual)"})
    if not vencen:
        return
    msg = "🔔 *Recordatorio: mañana vence...*\n\n"
    for g in vencen:
        msg += f"• *{g['nombre']}*: {g['monto']}\n  💳 {g['plataforma']}\n\n"
    msg += "¿Tenés la plata lista en la cuenta?"
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
    logger.info(f"Notificación enviada para día {dia}")

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
        g = spreadsheet.add_worksheet(title="Gastos", rows=1000, cols=9)
        g.append_row(["Fecha","Descripcion","Monto","Moneda","Categoria","Notas","Comprobante","Cliente","Estado"])
    else:
        # Agregar columna Estado si no existe
        ws = spreadsheet.worksheet("Gastos")
        headers = ws.row_values(1)
        if "Estado" not in headers:
            ws.resize(rows=1000, cols=len(headers)+1)
            ws.update_cell(1, len(headers)+1, "Estado")
    if "Vencimientos" not in sheet_names:
        v = spreadsheet.add_worksheet(title="Vencimientos", rows=100, cols=5)
        v.append_row(["Fecha Vencimiento","Descripcion","Monto","Moneda","Estado"])
    return spreadsheet

def marcar_agritest_cobrado(spreadsheet):
    ws = spreadsheet.worksheet("Gastos")
    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        return 0
    headers = all_values[0]
    try:
        cliente_col = headers.index("Cliente")
    except ValueError:
        return 0
    try:
        estado_col = headers.index("Estado")
    except ValueError:
        estado_col = len(headers)
        ws.update_cell(1, estado_col + 1, "Estado")
    count = 0
    cells = []
    for i, row in enumerate(all_values[1:], start=2):
        cliente = row[cliente_col] if len(row) > cliente_col else ""
        estado = row[estado_col] if len(row) > estado_col else ""
        if cliente == "Agritest" and estado.lower() in ("pendiente", ""):
            cells.append(gspread.Cell(i, estado_col + 1, "cobrado"))
            count += 1
    if cells:
        ws.update_cells(cells)
    return count

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
    save_chat_id(update.message.chat_id)
    await update.message.chat.send_action("typing")
    try:
        spreadsheet = get_sheet()
        data = get_recent_data(spreadsheet)
        gastos_mes = get_mes_actual(spreadsheet)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        fecha_hoy = datetime.now().strftime("%d/%m/%Y")

        system_prompt = f"""Sos un asistente financiero personal amigable que habla en espanol argentino (tuteo con vos).
Fecha actual: {datetime.now().strftime("%d/%m/%Y %H:%M")}

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

REGLAS IMPORTANTES:
1. Si el usuario dice "hoy" como fecha, usa: {fecha_hoy}
2. COMPROBANTE: "ticket" o "tengo ticket" -> "Ticket fisico". "screenshot", "captura", "foto" -> "Screenshot". "factura" -> "Factura". Sin mencion -> "". NUNCA pidas numero de ticket.
3. NO preguntes datos que el usuario ya dio. Si ya dijo fecha, categoria y comprobante, solo pedi lo que falta.
4. Si el mensaje tiene toda la info necesaria, registralo directamente SIN hacer preguntas.
5. CLIENTE: si el usuario dice "para agritest", cliente = "Agritest". Si es gasto personal, cliente = "". La categoria SIEMPRE debe ser la real (Comida, Transporte, etc.), NUNCA "Agritest".
6. DESCRIPCION: no incluyas "para Agritest" ni "Gasto para Agritest" en la descripcion, eso va en el campo cliente.
7. ESTADO: si cliente es "Agritest", estado = "pendiente". Si es gasto personal, estado = "".
8. COBRO AGRITEST: si el usuario dice que Agritest le pago, le deposito, cobro de Agritest, o similar → usar accion "cobro_agritest". Esto marca todos los gastos pendientes de Agritest como cobrados y reinicia el ciclo.

Para registrar gastos o vencimientos responde SOLO con JSON valido, sin backticks ni markdown:
{{"mensaje":"respuesta corta y amigable","accion":"gasto","datos":{{"fecha":"{fecha_hoy}","descripcion":"","monto":0,"moneda":"ARS","categoria":"Comida","notas":"","comprobante":"","cliente":"","estado":""}}}}

Valores de accion: gasto, vencimiento, cobro_agritest, consulta, ninguna
Categorias: Comida, Transporte, Servicios, Entretenimiento, Salud, Ropa, Ingreso, Otros
Para vencimientos usar: fecha_vencimiento, descripcion, monto, moneda, estado (Pendiente)
Para cobro_agritest los datos pueden ir vacios.
Para consultas y resumenes responde en texto natural con emojis, sin JSON."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )

        text = response.content[0].text.strip()
        logger.info(f"Claude response: {text[:200]}")

        try:
            if '{' in text:
                text = text[text.index('{'):text.rindex('}')+1]
                parsed = json.loads(text.strip())
                accion = parsed.get("accion","ninguna")
                datos = parsed.get("datos",{})
                mensaje = parsed.get("mensaje","Entendido!")

                if accion == "gasto" and datos:
                    spreadsheet.worksheet("Gastos").append_row([
                        datos.get("fecha", fecha_hoy),
                        datos.get("descripcion",""),
                        datos.get("monto",0),
                        datos.get("moneda","ARS"),
                        datos.get("categoria","Otros"),
                        datos.get("notas",""),
                        datos.get("comprobante",""),
                        datos.get("cliente",""),
                        datos.get("estado","")
                    ])
                    logger.info("Gasto guardado!")
                elif accion == "cobro_agritest":
                    count = marcar_agritest_cobrado(spreadsheet)
                    await update.message.reply_text(f"{mensaje}\n✅ Marqué {count} gasto(s) como cobrados. El ciclo Agritest arranca de cero.")
                    return
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
                await update.message.reply_text(text)

        except json.JSONDecodeError:
            await update.message.reply_text(text)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Ups, algo salio mal. Intenta de nuevo.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    app.job_queue.run_daily(daily_reminder, time=dtime(hour=9, minute=0, tzinfo=ARG_TZ))
    logger.info("Bot iniciado con notificaciones diarias a las 9 AM ARG!")
    app.run_polling()

if __name__ == "__main__":
    main()
