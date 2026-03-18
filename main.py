import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
from google import genai 
from google.genai import types 
from groq import Groq # <--- Tambahan: Import Groq
import time
import json
from datetime import datetime
import threading
import re

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
RAW_KEYS = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
# Tambahan: API Key Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Parsing Multiple Keys Gemini
ALL_KEYS = [k.strip() for k in RAW_KEYS.split(",")] if RAW_KEYS else []
current_key_index = 0

def get_client():
    """Mengambil client Gemini berdasarkan index rotasi saat ini"""
    global current_key_index
    if not ALL_KEYS:
        return None
    key = ALL_KEYS[current_key_index]
    return genai.Client(api_key=key)

def switch_key():
    """Berpindah ke API Key berikutnya jika terkena limit"""
    global current_key_index
    current_key_index = (current_key_index + 1) % len(ALL_KEYS)
    print(f"🔄 Berpindah ke API Key index: {current_key_index}")

# Model yang digunakan
MODEL_NAME = "gemini-2.0-flash"
GROQ_MODEL = "llama-3.3-70b-versatile" # <--- Model terbaik Groq

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

# --- AI ANALYSIS DENGAN AUTO-ROTATION & GROQ FALLBACK ---
def get_ai_analysis(coin_data, retry_count=0):
    # Jika Gemini habis, coba pakai Groq
    if retry_count >= len(ALL_KEYS):
        if GROQ_API_KEY:
            print(f"🚀 Gemini Limit. Mencoba Groq untuk {coin_data['symbol']}...")
            return get_groq_analysis(coin_data)
        print("❌ Semua API Key Gemini habis & Groq tidak tersedia.")
        return None

    symbol = coin_data['symbol']
    ict = get_ict_technical(symbol)
    price = coin_data.get('lastPrice') or coin_data.get('price')
    
    prompt = f"""
    Role: Expert ICT SMC Crypto Trader. Pair: {symbol} at {price}.
    Technical Bias: {ict['side'] if ict else 'Neutral'}.
    Task: Give trading signal in RAW JSON ONLY.
    {{
        "symbol": "{symbol}",
        "signal": "LONG/SHORT/WAIT",
        "entry": {price},
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0,
        "reason": "Expert analysis"
    }}
    """

    try:
        client = get_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json"
            )
        )
        
        if response.text:
            clean_json = response.text.strip()
            if "```" in clean_json:
                clean_json = re.sub(r'```json\n|```', '', clean_json)
            return json.loads(clean_json)
            
    except Exception as e:
        if "429" in str(e):
            print(f"⚠️ Key index {current_key_index} Limit! Mencoba key lain...")
            switch_key()
            time.sleep(2)
            return get_ai_analysis(coin_data, retry_count + 1)
        else:
            print(f"❌ Error AI {symbol}: {e}")
        return None

# --- TAMBAHAN: FUNGSI ANALISIS GROQ ---
def get_groq_analysis(coin_data):
    try:
        symbol = coin_data['symbol']
        price = coin_data.get('lastPrice') or coin_data.get('price')
        ict = get_ict_technical(symbol)
        
        client = Groq(api_key=GROQ_API_KEY)
        prompt = f"Role: Expert ICT SMC Trader. Pair: {symbol} at {price}. Bias: {ict['side'] if ict else 'Neutral'}. Give signal in RAW JSON ONLY: {{\"symbol\": \"{symbol}\", \"signal\": \"LONG/SHORT/WAIT\", \"entry\": {price}, \"tp1\": 0, \"tp2\": 0, \"tp3\": 0, \"sl\": 0, \"reason\": \"AI analysis\"}}"
        
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"❌ Error Groq {coin_data['symbol']}: {e}")
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
    print(f"🔍 Scan Market: {datetime.now().strftime('%H:%M:%S')}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 5000000]
    targets = sorted(targets, key=lambda x: float(x['quoteVolume']), reverse=True)[:7]
    
    for t in targets:
        try:
            sig = get_ai_analysis(t)
            if sig:
                send_signal_ui(sig)
            time.sleep(12) 
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
        bot.send_message(CHAT_ID, f"🔄 Menganalisis {sym} dengan AI...")
        
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={sym}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
            else: bot.send_message(CHAT_ID, "⚠️ AI belum menemukan setup valid.")
        else:
            bot.send_message(CHAT_ID, "❌ Koin tidak ditemukan.")
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ Error: {e}")

if __name__ == "__main__":
    if not ALL_KEYS:
        print("❌ ERROR: GEMINI_API_KEY tidak ditemukan!")
    else:
        print(f"✅ Bot Ready dengan {len(ALL_KEYS)} Gemini Keys & Groq Fallback.")
        try:
            bot.send_message(CHAT_ID, f"🏛️ **SMC System Online**\nKunci Gemini: {len(ALL_KEYS)}\nGroq: {'Aktif' if GROQ_API_KEY else 'Non-Aktif'}")
        except: pass
        
        threading.Thread(target=bot.infinity_polling, daemon=True).start()
        
        while True:
            run_scanner()
            print("💤 Scan selesai. Menunggu 30 menit...")
            time.sleep(1800)