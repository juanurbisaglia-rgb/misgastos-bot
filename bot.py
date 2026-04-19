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

# Config desde variables de entorno
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

# Inicializar Google Sheets
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    
    # Crear hojas si no existen
    sheet_names = [s.title for s in spreadsheet.worksheets()]
    
    if "Gastos" not in sheet_names:
        gastos = spreadsheet.add_worksheet(title="Gastos", rows=1000, cols=6)
        gastos.append_row(["Fecha", "Descripción", "Monto", "Moneda", "Categoría", "Notas"])
    
    if "Vencimientos" not in sheet_names:
        venc = spreadsheet.add_worksheet(title="Vencimientos", rows=100, cols=5)
        venc.append_row(["Fecha Vencimiento", "Descripción", "Monto", "Moneda", "Estado"])
    
    return spreadsheet

def get_gastos_sheet(spreadsheet):
    return spreadsheet.worksheet("Gastos")

def get_vencimientos_sheet(spreadsheet):
    return spreadsheet.worksheet("Vencimientos")

def get_recent_data(spreadsheet):
    """Obtiene los últimos gastos y vencimientos para dar contexto a Claude"""
    try:
        gastos = get_gastos_sheet(spreadsheet).get_all_values()
        vencimientos = get_vencimientos_sheet(spreadsheet).get_all_values()
        
        # Últimas 20 filas de gastos
        recent_gastos = gastos[-20:] if len(gastos) > 1 else [gastos[0]] if gastos else []
        
        return {
            "gastos_recientes": recent_gastos,
            "vencimientos": vencimientos
        }
    except:
        return {"gastos_recientes": [], "vencimientos": []}

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    
    await update.message.chat.send_action("typing")
    
    try:
        spreadsheet = get_sheet()
        data = get_recent_data(spreadsheet)
        
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        system_prompt = f"""Sos un asistente financiero personal amigable que habla en español argentino (tuteo con "vos").
        
Tu trabajo es ayudar al usuario a registrar gastos, ingresos y vencimientos. 

Fecha y hora actual: {datetime.now().strftime("%d/%m/%Y %H:%M")}

Datos actuales en la planilla:
- Últimos gastos: {json.dumps(data['gastos_recientes'], ensure_ascii=False)}
- Vencimientos: {json.dumps(data['vencimientos'], ensure_ascii=False)}

Cuando el usuario te diga algo, analizá si es:
1. Un GASTO o INGRESO → extraé fecha, descripción, monto, moneda (ARS/USD), categoría
2. Un VENCIMIENTO → extraé fecha de vencimiento, descripción, monto, moneda
3. Una CONSULTA → respondé con la info de la planilla

Siempre respondé en formato JSON con esta estructura:
{{
  "mensaje": "Tu respuesta amigable al usuario",
  "accion": "gasto" | "vencimiento" | "consulta" | "ninguna",
  "datos": {{
    // Para gasto:
    "fecha": "DD/MM/YYYY",
    "descripcion": "...",
    "monto": 1234.56,
    "moneda": "ARS" o "USD",
    "categoria": "Comida" | "Transporte" | "Servicios" | "Entretenimiento" | "Salud" | "Ropa" | "Otros",
    "notas": "..."
    
    // Para vencimiento:
    "fecha_vencimiento": "DD/MM/YYYY",
    "descripcion": "...",
    "monto": 1234.56,
    "moneda": "ARS" o "USD",
    "estado": "Pendiente"
  }}
}}

Ejemplos de mensajes del usuario y cómo interpretarlos:
- "gasté 5000 en uber" → gasto, transporte, ARS
- "compré 50 usd de ropa" → gasto, ropa, USD
- "vence el 25 la tarjeta por 80000" → vencimiento
- "cuánto gasté este mes" → consulta
- "me depositaron 200000 de sueldo" → gasto con monto positivo, categoría "Ingreso"

IMPORTANTE: Respondé SOLO con el JSON, sin texto adicional ni backticks."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        
        response_text = response.content[0].text.strip()
        
        # Limpiar posibles backticks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        logger.info(f"Claude response: {response_text}")
parsed = json.loads(response_text)
        
        mensaje = parsed.get("mensaje", "Entendido!")
        accion = parsed.get("accion", "ninguna")
        datos = parsed.get("datos", {})
        
        # Guardar en Google Sheets según la acción
        if accion == "gasto" and datos:
            sheet = get_gastos_sheet(spreadsheet)
            sheet.append_row([
                datos.get("fecha", datetime.now().strftime("%d/%m/%Y")),
                datos.get("descripcion", ""),
                datos.get("monto", 0),
                datos.get("moneda", "ARS"),
                datos.get("categoria", "Otros"),
                datos.get("notas", "")
            ])
        
        elif accion == "vencimiento" and datos:
            sheet = get_vencimientos_sheet(spreadsheet)
            sheet.append_row([
                datos.get("fecha_vencimiento", ""),
                datos.get("descripcion", ""),
                datos.get("monto", 0),
                datos.get("moneda", "ARS"),
                datos.get("estado", "Pendiente")
            ])
        
        await update.message.reply_text(mensaje)
        
    except json.JSONDecodeError:
        await update.message.reply_text("Anotado! ✅")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Ups, algo salió mal. Intentá de nuevo. 🙈")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_message))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
