import logging
import os
import requests
import matplotlib.pyplot as plt
from datetime import datetime
from io import BytesIO
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    ConversationHandler, filters
)
import texts
from dotenv import load_dotenv
import json
import time

load_dotenv()

# === API Keys ===
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CMC_API_KEY = os.getenv('CMC_API_KEY')

# === Стани діалогу ===
CHOOSE_COIN, CONVERT_FROM, CONVERT_AMOUNT, CONVERT_TO = range(4)

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Файловий кеш для списку монет CoinGecko ===
CACHE_FILE = "coingecko_cache.json"
CACHE_EXPIRATION = 3600  # 1 година в секундах

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > CACHE_EXPIRATION:
            return None
        return data.get("coins")
    except Exception as e:
        logging.error(f"Error loading cache: {e}")
        return None

def save_cache(coins):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "coins": coins}, f)
    except Exception as e:
        logging.error(f"Error saving cache: {e}")

# === Отримання CoinGecko ID із кешем ===
def get_coingecko_id(symbol):
    coins = load_cache()
    if coins is None:
        url = "https://api.coingecko.com/api/v3/coins/list"
        response = requests.get(url)
        if response.status_code != 200:
            return None
        coins = response.json()
        save_cache(coins)
    for coin in coins:
        if coin['symbol'].upper() == symbol.upper():
            return coin['id']
    return None

# === Побудова графіку ціни за 7 днів ===
def generate_price_chart(symbol: str):
    coingecko_id = get_coingecko_id(symbol)
    if not coingecko_id:
        return None
    url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart"
    params = {"vs_currency": "usd", "days": "7"}
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    data = r.json()
    prices = data.get("prices")
    if not prices:
        return None
    dates = [datetime.fromtimestamp(p[0] / 1000) for p in prices]
    values = [p[1] for p in prices]
    plt.figure(figsize=(8, 4))
    plt.plot(dates, values, label="USD", color="green")
    plt.title(f"{symbol.upper()} - ціна за 7 днів")
    plt.xlabel("Дата")
    plt.ylabel("USD")
    plt.grid(True)
    plt.tight_layout()
    buffer = BytesIO()
    plt.savefig(buffer, format="png")
    buffer.seek(0)
    plt.close()
    return buffer

# === Отримання аналітики монети ===
def get_crypto_analysis(symbol: str):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {'symbol': symbol.upper()}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return None
    data = response.json()
    try:
        quote = data['data'][symbol.upper()]['quote']['USD']
        price_raw = quote.get('price')
        if price_raw is None:
            return None
        if price_raw > 100:
            price = f"{price_raw:.2f}"
        elif 1 <= price_raw <= 100:
            price = f"{price_raw:.5f}"
        else:
            price = f"{price_raw:.6f}"
        percent_change_1h = round(quote.get('percent_change_1h', 0), 2)
        percent_change_24h = round(quote.get('percent_change_24h', 0), 2)
        percent_change_7d = round(quote.get('percent_change_7d', 0), 2)

        def analyze_change(label, value):
            if value > 5:
                return f"{label}: {texts.rapid_inc} (+{value}%)"
            elif value > 1:
                return f"{label}: {texts.stable_inc} (+{value}%)"
            elif -1 <= value <= 1:
                return f"{label}: {texts.stability} ({value}%)"
            elif value < -5:
                return f"{label}: {texts.rapid_dec} ({value}%)"
            else:
                return f"{label}: {texts.stable_dec} ({value}%)"

        analysis_text = "\n".join([
            f"\U0001F4B0 <b>{symbol.upper()}</b>\nЦіна: <b>{price}$</b>",
            analyze_change("1 година", percent_change_1h),
            analyze_change("24 години", percent_change_24h),
            analyze_change("7 днів", percent_change_7d),
        ])
        if percent_change_24h > 5:
            commentary = "Ціна демонструє сильне зростання за останню добу."
            recommendation = "Рекомендація: розгляньте можливість покупки або утримання."
        elif percent_change_24h < -5:
            commentary = "Криптовалюта переживає помітне падіння."
            recommendation = "Рекомендація: будьте обережні."
        elif -1 <= percent_change_24h <= 1:
            commentary = "На ринку спостерігається відносна стабільність."
            recommendation = "Рекомендація: спостерігайте за ринком."
        else:
            commentary = "Ринок показує помірну динаміку."
            recommendation = "Рекомендація: дійте обдумано."
        return f"{analysis_text}\n\n\U0001F9E0 <i>{commentary}</i>\n\n\U0001F4CC <b>{recommendation}</b>"
    except KeyError:
        return None

# === Топ-5 криптовалют ===
def get_top5_analysis():
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {'start': '1', 'limit': '5', 'convert': 'USD'}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return "⚠️ Помилка при отриманні даних."
    data = response.json()
    try:
        result = "\U0001F525 <b>Топ 5 криптовалют:</b>\n"
        for coin in data['data']:
            name = coin['name']
            symbol = coin['symbol']
            price_raw = coin['quote']['USD']['price']
            change_24h = coin['quote']['USD']['percent_change_24h']
            if price_raw > 100:
                price = f"{price_raw:.2f}"
            elif 1 <= price_raw <= 100:
                price = f"{price_raw:.5f}"
            else:
                price = f"{price_raw:.6f}"
            if change_24h > 5:
                analysis = texts.rapid_inc
            elif change_24h > 1:
                analysis = texts.stable_inc
            elif -1 <= change_24h <= 1:
                analysis = texts.stability
            elif change_24h < -5:
                analysis = texts.rapid_dec
            else:
                analysis = texts.stable_dec
            result += f"\n<b>{name} ({symbol})</b>\nЦіна: <b>{price}$</b>\n24г: {change_24h:.2f}% — {analysis}\n"
        return result
    except Exception:
        return "⚠️ Помилка при обробці даних."

# === Конвертація криптовалют ===
def convert_crypto_amount(from_symbol: str, to_symbol: str, amount: float):
    url = 'https://pro-api.coinmarketcap.com/v1/tools/price-conversion'
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {
        'amount': amount,
        'symbol': from_symbol.upper(),
        'convert': to_symbol.upper()
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return None
    data = response.json()
    try:
        result = data['data']
        converted_amount = result['quote'][to_symbol.upper()]['price']
        return f"{amount} {from_symbol.upper()} = {converted_amount:.6f} {to_symbol.upper()}"
    except Exception:
        return None

# === Головне меню ===
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("\U0001F4CA Топ-5 криптовалют")],
        [KeyboardButton("\U0001F50D Переглянути криптовалюту")],
        [KeyboardButton("\U0001F4B1 Конвертація криптовалют")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Оберіть дію:", reply_markup=reply_markup)

# === Обробка команди /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(texts.HELP_TEXT, parse_mode="HTML")
    await show_main_menu(update, context)

# === Обробка вибору кнопки ===
async def handle_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "\U0001F4CA Топ-5 криптовалют":
        result = get_top5_analysis()
        await update.message.reply_text(result, parse_mode="HTML")
        await show_main_menu(update, context)
    elif text == "\U0001F50D Переглянути криптовалюту":
        await update.message.reply_text("Введіть символ криптовалюти (наприклад BTC):", reply_markup=ReplyKeyboardRemove())
        return CHOOSE_COIN
    elif text == "\U0001F4B1 Конвертація криптовалют":
        await update.message.reply_text("Введіть символ валюти, з якої конвертуємо (наприклад BTC):", reply_markup=ReplyKeyboardRemove())
        return CONVERT_FROM

# === Обробка введення валюти, з якої конвертуємо ===
async def handle_convert_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from_symbol = update.message.text.strip().upper()
    context.user_data["from_symbol"] = from_symbol
    await update.message.reply_text("Введіть кількість валюти, яку конвертуємо:")
    return CONVERT_AMOUNT

# === Обробка введення кількості для конвертації ===
async def handle_convert_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        context.user_data["amount"] = amount
        await update.message.reply_text("Введіть символ валюти, у яку конвертуємо (наприклад USDT):")
        return CONVERT_TO
    except ValueError:
        await update.message.reply_text("⚠️ Введіть числове значення.")
        return CONVERT_AMOUNT

# === Обробка введення валюти, у яку конвертуємо ===
async def handle_convert_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    to_symbol = update.message.text.strip().upper()
    context.user_data["to_symbol"] = to_symbol
    from_symbol = context.user_data.get("from_symbol")
    amount = context.user_data.get("amount")
    result = convert_crypto_amount(from_symbol, to_symbol, amount)
    if result:
        await update.message.reply_text(result)
    else:
        await update.message.reply_text("⚠️ Не вдалося виконати конвертацію.\nПеревірте правильність написання токенів.\nТакож, можливо цих токенів поки немає в наших даних")
    await show_main_menu(update, context)
    return ConversationHandler.END

# === Обробка введення монети ===
async def handle_coin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.strip().upper()
    analysis = get_crypto_analysis(symbol)
    if analysis:
        await update.message.reply_text(analysis, parse_mode="HTML")
        chart = generate_price_chart(symbol)
        if chart:
            await update.message.reply_photo(photo=InputFile(chart, filename=f"{symbol}_7d.png"))
        else:
            await update.message.reply_text("⚠️ Не вдалося побудувати графік.\nМожливо для цього токену поки недостатньо інформації для побудови графіку.")
    else:
        await update.message.reply_text("⚠️ Не вдалося знайти інформацію про валюту.\nПеревірте правильність написання токену.\nТакож, можливо цього токену поки немає в наших даних")
    await show_main_menu(update, context)
    return ConversationHandler.END

# === Вихід з діалогу ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)
    return ConversationHandler.END

# === Запуск програми ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_choice)],
        states={
            CHOOSE_COIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coin_input)],
            CONVERT_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_convert_from)],
            CONVERT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_convert_amount)],
            CONVERT_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_convert_to)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
