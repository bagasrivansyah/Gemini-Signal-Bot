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
    print("✅ Gemini AI Terhubung (ICT SMC Agresif Active).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
active_signals = []

# --- TEKNIKAL ICT SMC ---
def get_htf_trend(symbol):
    """Cek trend di timeframe 4H untuk info di pesan"""
    data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=5")
    if not data: return "UNKNOWN"
    c4 = [float(x[4]) for x in data]
    return "BULLISH" if c4[-1] > c4[-2] else "BEARISH"

def get_ict_technical(symbol):
    """Mendeteksi FVG & Displacement (Mode Agresif)"""
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data or len(data) < 10: return None
        
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        current_vol = c[-2]['v']
        
        # Agresif: Lonjakan volume diturunkan ke 1.1x
        has_displacement = current_vol > (avg_vol * 1.1) 

        # Info trend HTF untuk pelengkap alasan AI
        htf = get_htf_trend(symbol)
        price = c[-1]['c']
        
        # Logika ICT: Bullish FVG (Tanpa blokir HTF)
        if c[-2]['l'] > c[-4]['h'] and has_displacement:
            swing_low = min([x['l'] for x in c[-10:-1]])
            return {"side": "LONG", "reason": f"BULLISH FVG + Vol Alert (HTF: {htf})", "sl": swing_low * 0.998, "price": price}
            
        # Logika ICT: Bearish FVG (Tanpa blokir HTF)
        if c[-2]['h'] < c[-4]['l'] and has_displacement:
            swing_high = max([x['h'] for x in c[-10:-1]])
            return {"side": "SHORT", "reason": f"BEARISH FVG + Vol Alert (HTF: {htf})", "sl": swing_high * 1.002, "price": price}
            
        return None
    except: return None

def call_binance_api(endpoint):
    endpoints = [
        "https://api.binance.com", "https://api1.binance.com", 
        "https://api2.binance.com", "https://api3.binance.com", 
        "https://data-api.binance.vision"
    ]
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    for base_url in endpoints:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, headers=headers, timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

def get_ai_analysis(coin):
    ict = get_ict_technical(coin['symbol'])
    if not ict: return None
    
    prompt = f"""
    Expert ICT SMC Trader: Analyze {coin['symbol']}.
    Current Price: {ict['price']}, Side: {ict['side']}, SL: {ict['sl']}, Reason: {ict['reason']}.
    Requirement: 20x Leverage. Calculate TP1 (RR 1:1), TP2 (RR 1:2), TP3 (RR 1:3).
    Return ONLY JSON:
    {{"symbol": "{coin['symbol']}", "signal": "{ict['side']}", "entry": {ict['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": {ict['sl']}, "reason": "{ict['reason']}"}}
    """
    try:
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        clean_text = response.text.strip().replace('```json', '').replace('```', '').split('{')[-1].split('}')[0]
        return json.loads('{' + clean_text + '}')
    except: return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    arrow = "▲" if sig_data['signal'] == "LONG" else "▼"
    
    msg = (
        f"🏛️ **ICT SMC PRO SIGNAL** 🏛️\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `20x Cross`\n"
        f"📈 **Side:** {sig_data['signal']} {arrow}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{sig_data['entry']}`\n"
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
    print(f"🔍 [{timestamp}] Memulai pemindaian SELURUH Market USDT...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        all_targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 300000]
        all_targets = sorted(all_targets, key=lambda x: float(x['quoteVolume']), reverse=True)
        
        print(f"Total koin dicek: {len(all_targets)}")
        
        found = False
        for t in all_targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
                print(f"✅ Sinyal Ditemukan: {t['symbol']}")
                time.sleep(0.1) 
                
        if not found: 
            print(f"🌑 [{timestamp}] Scan Selesai: Belum ada setup FVG.")
    except Exception as e:
        print(f"❌ Error saat scan: {e}")

# --- HANDLER PERINTAH TELEGRAM ---

@bot.message_handler(commands=['cek'])
def manual_check_coin(message):
    try:
        text_split = message.text.split()
        if len(text_split) < 2:
            bot.reply_to(message, "❌ Format salah. Gunakan: `/cek BTC` atau `/cek SOLUSDT`", parse_mode="Markdown")
            return
        
        coin_input = text_split[1].upper()
        symbol = coin_input if coin_input.endswith("USDT") else f"{coin_input}USDT"

        bot.send_message(CHAT_ID, f"🔄 Sedang menganalisis {symbol} dengan AI ICT SMC...")

        ticker_data = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        if not ticker_data:
            bot.send_message(CHAT_ID, f"❌ Koin {symbol} tidak ditemukan di Binance.")
            return

        # Coba analisa dengan logika ICT FVG
        sig = get_ai_analysis(ticker_data)
        
        if sig:
            send_signal_ui(sig)
        else:
            # Jika FVG tidak ada, minta AI prediksi berdasarkan harga saat ini
            price_now = ticker_data['lastPrice']
            prompt_umum = f"""
            As an Expert ICT SMC Trader, analyze {symbol} at price {price_now}. 
            No clear FVG found, but give your best bias (LONG/SHORT/WAIT) based on current price action.
            Calculate TP (RR 1:2) and SL for 20x leverage.
            Return ONLY JSON: 
            {{"symbol": "{symbol}", "signal": "TYPE", "entry": {price_now}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "AI Insight"}}
            """
            response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt_umum)
            clean_text = response.text.strip().replace('```json', '').replace('```', '').split('{')[-1].split('}')[0]
            sig_manual = json.loads('{' + clean_text + '}')
            send_signal_ui(sig_manual)
                
    except Exception as e:
        bot.send_message(CHAT_ID, f"⚠️ Error analisis: {str(e)}")

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Mencari Setup ICT SMC Agresif di Seluruh Market...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    bot.send_message(CHAT_ID, f"🤖 **SMC System:** Aktif (Agresif)\n📈 Sinyal Aktif: {len(active_signals)}\n👤 Developer: Bagas Rivansyah", parse_mode="Markdown")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

if __name__ == "__main__":
    try: 
        bot.remove_webhook()
        time.sleep(2) 
        bot.send_message(CHAT_ID, "🏛️ **SMC System Online (Scan & Manual Cek)!**", reply_markup=main_keyboard())
        print("✅ Bot Bagas Rivansyah Ready.")
    except: pass
    
    threading.Thread(target=bot.infinity_polling, kwargs={'timeout': 20}, daemon=True).start()
    
    last_scan = 0
    while True:
        if time.time() - last_scan > 600: 
            run_scanner()
            last_scan = time.time()
        time.sleep(10)
