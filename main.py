import os # Perbaikan: 'import' harus huruf kecil semua
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

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("✅ Gemini AI Terhubung (ICT SMC Agresif Active).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
active_signals = []

# --- TEKNIKAL ICT SMC ---
def get_htf_trend(symbol):
    data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=5")
    if not data: return "UNKNOWN"
    c4 = [float(x[4]) for x in data]
    return "BULLISH" if c4[-1] > c4[-2] else "BEARISH"

def get_ict_technical(symbol):
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data or len(data) < 10: return None
        
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        current_vol = c[-2]['v']
        
        has_displacement = current_vol > (avg_vol * 1.1) 
        htf = get_htf_trend(symbol)
        price = c[-1]['c']
        
        if c[-2]['l'] > c[-4]['h'] and has_displacement:
            swing_low = min([x['l'] for x in c[-10:-1]])
            return {"side": "LONG", "reason": f"BULLISH FVG (HTF: {htf})", "sl": swing_low * 0.998, "price": price}
            
        if c[-2]['h'] < c[-4]['l'] and has_displacement:
            swing_high = max([x['h'] for x in c[-10:-1]])
            return {"side": "SHORT", "reason": f"BEARISH FVG (HTF: {htf})", "sl": swing_high * 1.002, "price": price}
            
        return None
    except: return None

def call_binance_api(endpoint):
    # Menambah list endpoint untuk menghindari blokir IP
    endpoints = [
        "https://api.binance.com", 
        "https://api1.binance.com", 
        "https://api2.binance.com",
        "https://api3.binance.com"
    ]
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    for base_url in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

def get_ai_analysis(coin, custom_prompt=None):
    ict = get_ict_technical(coin['symbol'])
    
    if not custom_prompt:
        if not ict: return None
        prompt = f"""
        Expert ICT SMC Trader: Analyze {coin['symbol']}.
        Current Price: {ict['price']}, Side: {ict['side']}, SL: {ict['sl']}, Reason: {ict['reason']}.
        Requirement: 20x Leverage. TP1 (RR 1:1), TP2 (RR 1:2), TP3 (RR 1:3).
        Return ONLY JSON format:
        {{"symbol": "{coin['symbol']}", "signal": "{ict['side']}", "entry": {ict['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": {ict['sl']}, "reason": "{ict['reason']}"}}
        """
    else:
        prompt = custom_prompt

    try:
        # Nama model murni 'gemini-1.5-flash' untuk menghindari 404
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json'
            )
        )
        
        text = response.text.strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            return json.loads(text[start:end])
        return None
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    side = str(sig_data.get('signal', '')).upper()
    arrow = "▲" if "LONG" in side else "▼"
    
    msg = (
        f"🏛️ **ICT SMC PRO SIGNAL** 🏛️\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `20x Cross`\n"
        f"📈 **Side:** {side} {arrow}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{sig_data.get('entry', 0)}`\n"
        f"🎯 **TP 1:** `{sig_data.get('tp1', 0)}` (RR 1:1)\n"
        f"🔥 **TP 2:** `{sig_data.get('tp2', 0)}` (RR 1:2)\n"
        f"🚀 **TP 3:** `{sig_data.get('tp3', 0)}` (RR 1:3)\n"
        f"🛑 **Stop Loss:** `{sig_data.get('sl', 0)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"🔗 [VIEW CHART]({chart_url})\n"
        f"⚠️ *Bagas Rivansyah: Gunakan RM!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def run_scanner():
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"🔍 [{timestamp}] Memulai pemindaian Market USDT...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        all_targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 500000]
        all_targets = sorted(all_targets, key=lambda x: float(x['quoteVolume']), reverse=True)[:50]
        
        for t in all_targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                send_signal_ui(sig)
                time.sleep(1) 
    except Exception as e:
        print(f"❌ Error scan: {e}")

# --- HANDLER TELEGRAM ---
@bot.message_handler(commands=['cek'])
def manual_check_coin(message):
    try:
        text_split = message.text.split()
        if len(text_split) < 2:
            bot.reply_to(message, "❌ Format: `/cek BTC`", parse_mode="Markdown")
            return
        
        # Perbaikan: Bersihkan input dari 'USDT' berlebih jika user mengetik 'BTCUSDT'
        coin_raw = text_split[1].upper().replace("USDT", "")
        symbol = f"{coin_raw}USDT"
        
        bot.send_message(CHAT_ID, f"🔄 Menganalisis {symbol}...")

        ticker = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        if not ticker or 'lastPrice' not in ticker:
            bot.send_message(CHAT_ID, f"❌ {symbol} tidak ditemukan di Binance.")
            return

        price = ticker['lastPrice']
        prompt_cek = f"""
        Analyze {symbol} price {price} with ICT SMC. 
        Give bias (LONG/SHORT), Entry, SL, and 3 TPs for 20x leverage.
        Return ONLY JSON:
        {{"symbol": "{symbol}", "signal": "LONG", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "AI Analysis"}}
        """
        
        sig = get_ai_analysis(ticker, custom_prompt=prompt_cek)
        if sig: send_signal_ui(sig)
        else: bot.send_message(CHAT_ID, "⚠️ Gagal mendapatkan analisis AI.")
    except Exception as e:
        bot.send_message(CHAT_ID, f"⚠️ Error: {e}")

@bot.message_handler(func=lambda m: m.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Mencari Setup ICT SMC...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == '📊 Status Bot')
def bot_status(message):
    bot.send_message(CHAT_ID, f"🤖 **SMC System:** Aktif\n👤 Developer: Bagas Rivansyah", parse_mode="Markdown")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('🔍 Scan Market Sekarang', '📊 Status Bot')
    return markup

if __name__ == "__main__":
    # Kirim pesan status saat bot mulai
    try:
        bot.send_message(CHAT_ID, "🏛️ **SMC System Online (Fix 404 & Import)!**", reply_markup=main_keyboard())
        print("✅ Bot Bagas Rivansyah Ready.")
    except: pass
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    last_scan = 0
    while True:
        if time.time() - last_scan > 900: 
            run_scanner()
            last_scan = time.time()
        time.sleep(10)
