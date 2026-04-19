# 💰 MisGastos Bot

Bot de Telegram para registrar gastos y vencimientos automáticamente en Google Sheets.

## Variables de entorno necesarias en Railway:

| Variable | Valor |
|----------|-------|
| `TELEGRAM_TOKEN` | El token de tu bot de Telegram |
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic |
| `SPREADSHEET_ID` | El ID de tu Google Sheet |
| `GOOGLE_CREDENTIALS_JSON` | El contenido completo del archivo JSON de credenciales |

## Cómo usar el bot:

- "gasté 5000 en uber" → registra un gasto
- "compré 50 usd de ropa" → registra gasto en dólares
- "vence el 25 la tarjeta por 80000" → registra vencimiento
- "cuánto gasté este mes" → consulta tus gastos
- "me depositaron 200000 de sueldo" → registra ingreso
