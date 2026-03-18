import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
from google import genai 
import time
import json
from datetime import datetime
import threading

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN TELEGRAM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("✅ Gemini AI Terhubung (Mode Agresif Aktif).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]
active_signals = []

def call_binance_api(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200: return response.json()
        except: continue
    return None

def get_technical_data(symbol):
    try:
        # Ambil data 15m & 1h (4h opsional agar lebih cepat muncul sinyal)
        d15m = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=15m&limit=50")
        d1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        
        if not d15m or not d1h: return None
        
        df15 = pd.DataFrame(d15m, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df15['close'] = df15['c'].astype(float)
        df15['ema_9'] = ta.ema(df15['close'], length=9)
        df15['ema_21'] = ta.ema(df15['close'], length=21)
        
        ema21_1h = ta.ema(pd.Series([float(x[4]) for x in d1h]), length=21).iloc[-1]
        current_price = df15['close'].iloc[-1]
        
        # LOGIKA: Fokus pada 15m & 1h agar sinyal lebih sering muncul
        is_bull = (current_price > ema21_1h) or (df15['ema_9'].iloc[-1] > df15['ema_21'].iloc[-1])
        is_bear = (current_price < ema21_1h) or (df15['ema_9'].iloc[-1] < df15['ema_21'].iloc[-1])
        
        trend = "UP" if is_bull else "DOWN" if is_bear else "SIDELINES"
        
        vol_ratio = round(float(df15['v'].iloc[-1]) / df15['v'].astype(float).iloc[-21:-1].mean(), 2)
        
        return {"trend": trend, "price": current_price, "vol_spike": f"{vol_ratio}x"}
    except: return None

def get_ai_analysis(coin):
    tech = get_technical_data(coin['symbol'])
    if not tech or tech['trend'] == "SIDELINES": return None
    
    # Prompt lebih to-the-point agar JSON tidak error
    prompt = f"Expert Scalper: Analyze {coin['symbol']} at {tech['price']}. Trend: {tech['trend']}. Vol: {tech['vol_spike']}. Give 20x Leverage signal. Return ONLY JSON: {{\"symbol\": \"{coin['symbol']}\", \"signal\": \"{tech['trend']}\", \"entry\": {tech['price']}, \"tp1\": 0, \"tp2\": 0, \"tp3\": 0, \"sl\": 0, \"reason\": \"Trend alignment\"}}"
    
    try:
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        # Pembersihan JSON yang lebih kuat
        clean_text = response.text.strip().replace('```json', '').replace('```', '').split('{')[-1].split('}')[0]
        return json.loads('{' + clean_text + '}')
    except: return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    
    msg = (
        f"🔥 **FAST SCALPING SIGNAL** 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol}\n"
        f"📈 **Type:** {sig_data['signal']} | 20x\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Entry:** {sig_data['entry']}\n"
        f"✅ **TP1:** {sig_data.get('tp1', 0)}\n"
        f"🛑 **SL:** {sig_data.get('sl', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"🔗 [LIHAT CHART]({chart_url})\n"
        f"⚠️ *Bagas Rivansyah: Gunakan RM!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def run_scanner():
    print("🔍 Scanning Market...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        # Filter volume diturunkan ke 20.000 agar lebih banyak koin terdeteksi
        targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 20000]
        targets = sorted(targets, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)[:15]
        
        found = False
        for t in targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
        if not found: bot.send_message(CHAT_ID, "🔍 Selesai: Momentum belum cukup kuat.")
    except: pass

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Mencari momentum scalping...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    bot.send_message(CHAT_ID, f"🤖 **Status:** Aktif\n📈 Sinyal Aktif: {len(active_signals)}\n👤 Developer: Bagas Rivansyah", parse_mode="Markdown")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

if __name__ == "__main__":
    try: bot.send_message(CHAT_ID, "🚀 **Bot Online!**", reply_markup=main_keyboard())
    except: pass
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    last_scan = 0
    while True:
        if time.time() - last_scan > 600:
            run_scanner()
            last_scan = time.time()
        time.sleep(10)
