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
import re

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN_TELEGRAM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")

# --- INISIALISASI CLIENT GEMINI 2.0 ---
try:
    # Menggunakan Gemini 2.0 Flash (Terbaru & Tercepat)
    client = genai.Client(api_key=GEMINI_API_KEY)
    MODEL_NAME = "gemini-2.0-flash" 
    print(f"✅ Gemini AI System Connected ({MODEL_NAME}).")
except Exception as e:
    print(f"❌ Gagal Inisialisasi AI: {e}")

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

# --- AI ANALYSIS (FIXED & STABLE) ---
def get_ai_analysis(coin_data):
    symbol = coin_data['symbol']
    ict = get_ict_technical(symbol)
    price = coin_data.get('lastPrice') or coin_data.get('price')
    
    # Prompt lebih ketat agar output selalu valid JSON
    prompt = f"""
    Role: Expert ICT SMC Crypto Trader.
    Analyze: {symbol} current price {price}.
    Technical Bias: {ict['side'] if ict else 'Neutral'}, Reason: {ict['reason'] if ict else 'Price Action Market Structure'}.
    
    Task: Give a trading signal. 
    Return ONLY a raw JSON object with this exact keys:
    {{"symbol": "{symbol}", "signal": "LONG", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "Short expert logic"}}
    Note: Signal must be "LONG", "SHORT", or "WAIT". No markdown tags.
    """

    try:
        # Menggunakan Model Terbaru Gemini 2.0 Flash
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json" # Memaksa output JSON
            )
        )
        
        if response.text:
            # Pembersihan tambahan jika AI masih memberikan markdown
            clean_json = response.text.strip()
            if "```json" in clean_json:
                clean_json = re.search(r'```json\n(.*?)\n```', clean_json, re.DOTALL).group(1)
            elif "```" in clean_json:
                clean_json = clean_json.replace("```", "")
                
            return json.loads(clean_json)
            
    except Exception as e:
        print(f"❌ Error Analysis {symbol}: {e}")
        return None

def send_signal_ui(sig_data):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    
    symbol = sig_data.get('symbol')
    side = "🟢 LONG" if sig_data.get('signal') == "LONG" else "🔴 SHORT"
    
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
    print(f"🔍 Memulai Scan Market: {datetime.now().strftime('%H:%M:%S')}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    # Filter koin dengan volume tinggi (> 10jt USDT untuk keamanan)
    targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 10000000]
    # Ambil 10 koin teratas berdasarkan volume
    targets = sorted(targets, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
    
    for t in targets:
        try:
            sig = get_ai_analysis(t)
            if sig:
                send_signal_ui(sig)
            time.sleep(2) # Jeda singkat agar tidak kena rate limit API
        except:
            continue

@bot.message_handler(commands=['cek'])
def manual_check(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Gunakan: /cek BTC")
            return
            
        sym = parts[1].upper()
        sym = f"{sym}USDT" if not sym.endswith("USDT") else sym
        bot.send_message(CHAT_ID, f"🔄 Sedang menganalisis {sym}...")
        
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={sym}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
            else: bot.send_message(CHAT_ID, "⚠️ AI tidak melihat peluang saat ini.")
        else:
            bot.send_message(CHAT_ID, "❌ Koin tidak ditemukan di Binance.")
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ Error: {e}")

if __name__ == "__main__":
    try:
        bot.send_message(CHAT_ID, "🏛️ **SMC System Online (Gemini 2.0 Flash)**\nDev: Bagas Rivansyah")
        print("✅ Bot Ready.")
    except: pass
    
    # Menjalankan Polling Telegram di Thread terpisah
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    # Loop Scanner Utama
    while True:
        run_scanner()
        print("💤 Scan selesai. Menunggu 30 menit...")
        time.sleep(1800) # Scan ulang setiap 30 menit