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
    print("✅ Gemini AI Terhubung (ICT SMC Mode Active).")
except Exception as e:
    print(f"❌ Gagal AI: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]
active_signals = []

# --- TEKNIKAL ICT SMC ---
def get_htf_trend(symbol):
    """Cek trend di timeframe 4H untuk konfirmasi arah besar"""
    data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=5")
    if not data: return None
    c4 = [float(x[4]) for x in data]
    return "BULLISH" if c4[-1] > c4[-2] else "BEARISH"

def get_ict_technical(symbol):
    """Mendeteksi FVG, Displacement, dan Swing Points"""
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data or len(data) < 10: return None
        
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        current_vol = c[-2]['v']
        has_displacement = current_vol > (avg_vol * 1.5) 

        htf = get_htf_trend(symbol)
        price = c[-1]['c']
        
        # Logika ICT: Fair Value Gap (FVG)
        if htf == "BULLISH" and c[-2]['l'] > c[-4]['h'] and has_displacement:
            swing_low = min([x['l'] for x in c[-10:-1]])
            return {"side": "LONG", "reason": "BULLISH FVG + Displacement + HTF", "sl": swing_low * 0.998, "price": price}
            
        if htf == "BEARISH" and c[-2]['h'] < c[-4]['l'] and has_displacement:
            swing_high = max([x['h'] for x in c[-10:-1]])
            return {"side": "SHORT", "reason": "BEARISH FVG + Displacement + HTF", "sl": swing_high * 1.002, "price": price}
            
        return None
    except: return None

def call_binance_api(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
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

# --- UPDATED SCANNER WITH LOGGING ---
def run_scanner():
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"🔍 [{timestamp}] Memulai pemindaian ICT SMC...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: 
            print("⚠️ Gagal mengambil data Binance.")
            return
        
        targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 500000]
        targets = sorted(targets, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)[:15]
        
        found = False
        for t in targets:
            # Log deteksi per koin untuk debugging Railway
            print(f"🧐 Mengecek: {t['symbol']} | Volume: {float(t['quoteVolume']):,.0f}")
            
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
                print(f"✅ Sinyal Ditemukan: {t['symbol']}")
                
        if not found: 
            print("🌑 Scan Selesai: Tidak ada koin memenuhi kriteria FVG.")
            bot.send_message(CHAT_ID, "🔍 Selesai: Setup ICT (FVG) belum ditemukan.")
    except Exception as e:
        print(f"❌ Error saat scan: {e}")

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Mencari Setup ICT SMC Pro...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    bot.send_message(CHAT_ID, f"🤖 **SMC System:** Aktif\n🎯 **Mode:** ICT FVG + Displacement\n📈 Sinyal Aktif: {len(active_signals)}\n👤 Developer: Bagas Rivansyah", parse_mode="Markdown")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

if __name__ == "__main__":
    try: 
        bot.remove_webhook() # Menghindari Error 409 Conflict
        time.sleep(1)
        bot.send_message(CHAT_ID, "🏛️ **SMC Trading System Online!**", reply_markup=main_keyboard())
    except: pass
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    last_scan = 0
    while True:
        if time.time() - last_scan > 900: 
            run_scanner()
            last_scan = time.time()
        time.sleep(10)
