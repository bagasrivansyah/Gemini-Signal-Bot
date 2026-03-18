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

# --- INISIALISASI CLIENT STABLE ---
try:
    # Menggunakan v1 (Stable) untuk menghindari bug 404 pada v1beta
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={'api_version': 'v1'} 
    )
    print("✅ Gemini AI System Connected (Stable Mode).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- SISTEM KONEKSI BINANCE ---
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
        
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        if c[-2]['v'] > (avg_vol * 1.2):
            if c[-2]['l'] > c[-4]['h']:
                return {"side": "LONG", "reason": "BULLISH FVG", "sl": min([x['l'] for x in c[-5:]]), "price": price}
            if c[-2]['h'] < c[-4]['l']:
                return {"side": "SHORT", "reason": "BEARISH FVG", "sl": max([x['h'] for x in c[-5:]]), "price": price}
        return None
    except: return None

# --- AI ANALYSIS (ANTI-ERROR FALLBACK) ---
def get_ai_analysis(coin_data, custom_prompt=None):
    symbol = coin_data['symbol']
    ict = get_ict_technical(symbol)
    price = coin_data.get('lastPrice') or coin_data.get('price')
    
    prompt = custom_prompt or f"""
    Role: Expert ICT SMC Trader. Pair: {symbol} at {price}.
    Bias: {ict['side'] if ict else 'Neutral'}, Logic: {ict['reason'] if ict else 'Price Action'}.
    Return ONLY JSON:
    {{"symbol": "{symbol}", "signal": "LONG/SHORT", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "AI Logic"}}
    """

    # Percobaan 1: Menggunakan Mode JSON Formal (Bisa kena error 400 di bbrp region)
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        if response.text:
            return json.loads(response.text.strip())
    except Exception as e:
        print(f"⚠️ Jalur JSON Error, mencoba jalur Fallback untuk {symbol}...")

    # Percobaan 2: Jalur Fallback (Tanpa config JSON, kita bersihkan manual)
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt + " (Output must be RAW JSON only)"
        )
        if response.text:
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_json)
    except Exception as e2:
        print(f"❌ Gemini Gagal Total ({symbol}): {e2}")
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
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{sig_data.get('entry')}`\n"
        f"🎯 **TP1:** `{sig_data.get('tp1')}`\n"
        f"🛑 **SL:** `{sig_data.get('sl')}`\n"
        f"💡 **AI:** {sig_data.get('reason')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Dev: Bagas Rivansyah*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def run_scanner():
    print(f"🔍 Scan Market: {datetime.now().strftime('%H:%M:%S')}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    # Ambil 10 koin dengan volume tertinggi
    targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 5000000]
    targets = sorted(targets, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
    
    for t in targets:
        sig = get_ai_analysis(t)
        if sig and sig.get('signal') in ['LONG', 'SHORT']:
            send_signal_ui(sig)
            time.sleep(5) # Jeda antar koin agar tidak spam

@bot.message_handler(commands=['cek'])
def manual_check(message):
    try:
        sym = message.text.split()[1].upper()
        sym = f"{sym}USDT" if "USDT" not in sym else sym
        bot.send_message(CHAT_ID, f"🔄 Membedah {sym} dengan AI Bagas Rivansyah...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={sym}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
            else: bot.send_message(CHAT_ID, "⚠️ AI tidak menemukan setup valid.")
        else: bot.send_message(CHAT_ID, "❌ Koin tidak ditemukan.")
    except: bot.send_message(CHAT_ID, "Gunakan: /cek BTC")

if __name__ == "__main__":
    try:
        bot.send_message(CHAT_ID, "🏛️ **SMC System Bagas Rivansyah Online!**")
        print("✅ Bot Bagas Rivansyah Ready.")
    except: pass
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        run_scanner()
        time.sleep(1800) # Scan setiap 30 menit
