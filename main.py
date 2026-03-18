import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
from google import genai 
from google.genai import types 
import time
import json
from datetime import datetime
import threading

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN TELEGRAM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")

# --- INISIALISASI CLIENT (STABLE FOR RAILWAY) ---
try:
    # Jangan pakai v1beta di http_options jika masih 404, biarkan default SDK yang mengatur
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("✅ Gemini AI System Connected (Bagas Rivansyah Edition).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- SISTEM KONEKSI BINANCE (RETRY LOGIC) ---
def call_binance_api(endpoint):
    endpoints = [
        "https://api.binance.com",
        "https://api3.binance.com",
        "https://data-api.binance.vision"
    ]
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    for base_url in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

# --- TEKNIKAL ICT SMC ---
def get_ict_technical(symbol):
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data or len(data) < 10: return None
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        price = c[-1]['c']
        # Displacement check
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        if c[-2]['v'] > (avg_vol * 1.2):
            if c[-2]['l'] > c[-4]['h']:
                return {"side": "LONG", "reason": "BULLISH FVG", "sl": min([x['l'] for x in c[-5:]]), "price": price}
            if c[-2]['h'] < c[-4]['l']:
                return {"side": "SHORT", "reason": "BEARISH FVG", "sl": max([x['h'] for x in c[-5:]]), "price": price}
        return None
    except: return None

# --- AI ANALYSIS (PERBAIKAN PATH MODEL) ---
def get_ai_analysis(coin_data, custom_prompt=None):
    symbol = coin_data['symbol']
    ict = get_ict_technical(symbol)
    price = coin_data.get('lastPrice') or coin_data.get('price')
    
    prompt = custom_prompt or f"""
    Role: Expert ICT SMC Trader. Pair: {symbol} at {price}.
    Bias: {ict['side'] if ict else 'Neutral'}, Logic: {ict['reason'] if ict else 'Price Action'}.
    Requirement: 20x Leverage. Return ONLY JSON:
    {{"symbol": "{symbol}", "signal": "LONG/SHORT", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "AI Logic"}}
    """

    try:
        # PERBAIKAN KRITIS: Gunakan 'models/gemini-1.5-flash' (Wajib pakai prefix 'models/')
        # Jika tetap 404, gunakan 'models/gemini-1.5-flash-latest'
        response = client.models.generate_content(
            model='models/gemini-1.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        if response.text:
            return json.loads(response.text.strip())
        return None
    except Exception as e:
        print(f"❌ Kesalahan Gemini ({symbol}): {e}")
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal')).upper()
    msg = (
        f"🏛️ **ICT SMC PRO SIGNAL**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `20x`\n"
        f"📈 **Side:** {side}\n"
        f"💎 **Entry:** `{sig_data.get('entry')}`\n"
        f"🎯 **TP1:** `{sig_data.get('tp1')}`\n"
        f"🛑 **SL:** `{sig_data.get('sl')}`\n"
        f"💡 **AI:** {sig_data.get('reason')}\n"
        f"👤 *Dev: Bagas Rivansyah*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def run_scanner():
    print(f"🔍 Scan Market: {datetime.now().strftime('%H:%M:%S')}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 5000000][:15]
    for t in targets:
        sig = get_ai_analysis(t)
        if sig and sig.get('signal') in ['LONG', 'SHORT']:
            send_signal_ui(sig)
            time.sleep(2)

@bot.message_handler(commands=['cek'])
def manual_check(message):
    try:
        sym = message.text.split()[1].upper()
        sym = f"{sym}USDT" if "USDT" not in sym else sym
        bot.send_message(CHAT_ID, f"🔄 Membedah {sym}...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={sym}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
            else: bot.send_message(CHAT_ID, "⚠️ AI tidak memberikan sinyal valid.")
        else: bot.send_message(CHAT_ID, "❌ Koin tidak valid.")
    except: bot.send_message(CHAT_ID, "Gunakan: /cek BTC")

if __name__ == "__main__":
    bot.send_message(CHAT_ID, "🏛️ **SMC System Bagas Rivansyah Online!**")
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    while True:
        run_scanner()
        time.sleep(1800)
