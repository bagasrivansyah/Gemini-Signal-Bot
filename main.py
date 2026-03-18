import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
RAW_KEYS = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

from google import genai 
from google.genai import types 
from groq import Groq 

# Database sederhana (In-Memory)
ACTIVE_SIGNALS = []
TRADE_HISTORY = [] # Menyimpan trade yang sudah selesai hari ini
LEVERAGE = 20

# Parsing Multiple Keys Gemini
ALL_KEYS = [k.strip() for k in RAW_KEYS.split(",")] if RAW_KEYS else []
current_key_index = 0

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- FUNGSI FORMAT HARGA ---
def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

# --- SISTEM KONEKSI BINANCE ---
def call_binance_api(endpoint):
    endpoints = ["https://api.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]
    for base_url in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

def get_client():
    global current_key_index
    if not ALL_KEYS: return None
    return genai.Client(api_key=ALL_KEYS[current_key_index])

def switch_key():
    global current_key_index
    current_key_index = (current_key_index + 1) % len(ALL_KEYS)
    print(f"🔄 Berpindah ke API Key index: {current_key_index}")

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

# --- AI ANALYSIS ---
def get_ai_analysis(coin_data, retry_count=0):
    symbol = coin_data['symbol']
    price = float(coin_data.get('lastPrice') or coin_data.get('price'))
    
    if retry_count >= len(ALL_KEYS):
        if GROQ_API_KEY: return get_groq_analysis(coin_data)
        return None

    ict = get_ict_technical(symbol)
    prompt = f"""
    Role: Expert ICT SMC Trader. Pair: {symbol} at {format_price(price)}.
    Task: Berikan trading signal RAW JSON. Wajib TP1, TP2, TP3, dan SL. 
    Format JSON: {{"symbol": "{symbol}", "signal": "LONG/SHORT/WAIT", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "..."}}
    """
    try:
        client = get_client()
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json"))
        data = json.loads(response.text.strip())
        return data
    except Exception as e:
        if "429" in str(e):
            switch_key()
            return get_ai_analysis(coin_data, retry_count + 1)
        return None

def get_groq_analysis(coin_data):
    try:
        symbol = coin_data['symbol']
        price = float(coin_data.get('lastPrice') or coin_data.get('price'))
        client = Groq(api_key=GROQ_API_KEY)
        prompt = f"Expert SMC Trader. Pair: {symbol} at {price}. Give signal JSON with tp1, tp2, tp3, sl."
        completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- MONITORING TP/SL & ROI ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, TRADE_HISTORY
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol = sig['symbol']
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                
                curr_price = float(res['price'])
                entry = float(sig['entry'])
                side = sig['signal'].upper()
                
                roi = 0
                is_hit = False
                status = ""

                if (side == "LONG" and curr_price <= float(sig['sl'])) or (side == "SHORT" and curr_price >= float(sig['sl'])):
                    roi = -100 
                    status = "🛑 SL HIT"
                    is_hit = True
                
                elif (side == "LONG" and curr_price >= float(sig['tp3'])) or (side == "SHORT" and curr_price <= float(sig['tp3'])):
                    roi = abs((curr_price - entry) / entry) * 100 * LEVERAGE
                    status = "🎯 TP3 HIT (MAX)"
                    is_hit = True
                
                elif (side == "LONG" and curr_price >= float(sig['tp1'])) or (side == "SHORT" and curr_price <= float(sig['tp1'])):
                    if "tp1_notified" not in sig:
                        bot.send_message(CHAT_ID, f"✅ **TP1 REACHED**\n#{symbol}\nPrice: {format_price(curr_price)}")
                        sig['tp1_notified'] = True

                if is_hit:
                    msg = f"{status}\n━━━━━━━━━━━━━━\n🪙 #{symbol}\n📈 ROI: {roi:,.2f}%\n💵 Exit: {format_price(curr_price)}"
                    bot.send_message(CHAT_ID, msg)
                    sig['roi'] = roi
                    sig['exit_price'] = curr_price
                    sig['close_time'] = datetime.now()
                    TRADE_HISTORY.append(sig)
                    ACTIVE_SIGNALS.remove(sig)
            
            time.sleep(60) 
        except Exception as e:
            print(f"Monitor Error: {e}")
            time.sleep(60)

# --- LAPORAN HARIAN ---
def send_daily_report():
    global TRADE_HISTORY
    while True:
        now = datetime.utcnow()
        if now.hour == 0 and now.minute == 0:
            if not TRADE_HISTORY:
                bot.send_message(CHAT_ID, "📊 **Laporan Harian**\nTidak ada trade selesai hari ini.")
            else:
                total_roi = sum([t['roi'] for t in TRADE_HISTORY])
                wins = len([t for t in TRADE_HISTORY if t['roi'] > 0])
                total = len(TRADE_HISTORY)
                
                report = (
                    f"📊 **LAPORAN HARIAN SMC AI**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Total Trade: {total}\n"
                    f"🏆 Winrate: {(wins/total)*100:.1f}%\n"
                    f"💰 Total ROI: {total_roi:,.2f}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Semoga besok lebih cuan!"
                )
                bot.send_message(CHAT_ID, report)
                TRADE_HISTORY = [] 
            time.sleep(70) 
        time.sleep(30)

# --- UI & SCANNER ---
def send_signal_ui(sig_data):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    symbol = sig_data['symbol']
    side = "🟢 LONG" if sig_data['signal'] == "LONG" else "🔴 SHORT"
    
    # Generate TradingView Link
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    msg = (
        f"🏛️ **ICT SMC PRO SIGNAL**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `{LEVERAGE}x`\n"
        f"📈 **Side:** {side}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{format_price(sig_data['entry'])}`\n"
        f"🎯 **TP1:** `{format_price(sig_data['tp1'])}`\n"
        f"🎯 **TP2:** `{format_price(sig_data['tp2'])}`\n"
        f"🎯 **TP3:** `{format_price(sig_data['tp3'])}`\n"
        f"🛑 **SL:** `{format_price(sig_data['sl'])}`\n"
        f"💡 **AI:** {sig_data['reason']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 [Lihat Chart TradingView]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Dev: Bagas Rivansyah*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)
    ACTIVE_SIGNALS.append(sig_data) 

def run_scanner():
    print(f"🔍 Scanning Market: {datetime.now()}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    valid = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 5000000]
    gainers = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:4]
    losers = sorted(valid, key=lambda x: float(x['priceChangePercent']))[:4]
    trending = sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:4]
    
    targets = {t['symbol']: t for t in (gainers + losers + trending)}.values()
    for t in targets:
        try:
            if any(s['symbol'] == t['symbol'] for s in ACTIVE_SIGNALS): continue
            
            sig = get_ai_analysis(t)
            if sig: send_signal_ui(sig)
            time.sleep(15) 
        except: continue

@bot.message_handler(commands=['cek'])
def manual_check(message):
    try:
        sym = message.text.split()[1].upper()
        sym = f"{sym}USDT" if not sym.endswith("USDT") else sym
        bot.send_message(CHAT_ID, f"🔄 Menganalisis {sym}...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={sym}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
        else: bot.send_message(CHAT_ID, "❌ Koin tidak ditemukan.")
    except: bot.reply_to(message, "Gunakan: /cek BTC")

if __name__ == "__main__":
    print("✅ Bot SMC Pro System Starting...")
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=send_daily_report, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        run_scanner()
        time.sleep(1800)