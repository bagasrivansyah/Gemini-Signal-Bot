import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone
from telebot.types import ReplyKeyboardMarkup, KeyboardButton # Tambahan untuk tombol
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Database sederhana (In-Memory)
ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
LEVERAGE = 20

# Blacklist Koin Stable agar tidak dianalisa
STABLE_COINS = [
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", 
    "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "PAXGUSDT", "USDTUSDT"
]

# Model Configuration Groq
GROQ_MODEL = "llama-3.3-70b-versatile"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- FUNGSI TOMBOL MENU ---
def main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("🔍 Scan Market Sekarang"),
        KeyboardButton("📊 Status Bot")
    )
    return markup

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

# --- AI ANALYSIS (GROQ ONLY) ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data['symbol']
    price = float(coin_data.get('lastPrice') or coin_data.get('price'))
    ict = get_ict_technical(symbol)
    
    prompt = f"""
    Role: Expert ICT SMC Crypto Trader. Pair: {symbol} at {format_price(price)}.
    Technical Bias: {ict['side'] if ict else 'Neutral'}.
    Task: Berikan trading signal RAW JSON. Wajib TP1, TP2, TP3, dan SL.
    Dilarang menggunakan scientific notation (e-07).
    JSON: {{"symbol": "{symbol}", "signal": "LONG/SHORT/WAIT", "entry": {price}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "reason": "Expert analysis singkat"}}
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
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
                
                is_hit = False
                if (side == "LONG" and curr_price <= float(sig['sl'])) or (side == "SHORT" and curr_price >= float(sig['sl'])):
                    sig['roi'] = -100
                    status = "🛑 SL HIT"
                    is_hit = True
                elif (side == "LONG" and curr_price >= float(sig['tp3'])) or (side == "SHORT" and curr_price <= float(sig['tp3'])):
                    sig['roi'] = abs((curr_price - entry) / entry) * 100 * LEVERAGE
                    status = "🎯 TP3 HIT (MAX)"
                    is_hit = True
                elif (side == "LONG" and curr_price >= float(sig['tp1'])) or (side == "SHORT" and curr_price <= float(sig['tp1'])):
                    if "tp1_notified" not in sig:
                        bot.send_message(CHAT_ID, f"✅ **TP1 REACHED**\n#{symbol}\nPrice: {format_price(curr_price)}")
                        sig['tp1_notified'] = True

                if is_hit:
                    msg = f"{status}\n━━━━━━━━━━━━━━\n🪙 #{symbol}\n📈 ROI: {sig['roi']:,.2f}%\n💵 Exit: {format_price(curr_price)}"
                    bot.send_message(CHAT_ID, msg)
                    sig['close_time'] = datetime.now(timezone.utc)
                    TRADE_HISTORY.append(sig)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

# --- LAPORAN HARIAN ---
def send_daily_report():
    global TRADE_HISTORY
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute == 0:
            if TRADE_HISTORY:
                total_roi = sum([t['roi'] for t in TRADE_HISTORY])
                wins = len([t for t in TRADE_HISTORY if t['roi'] > 0])
                total = len(TRADE_HISTORY)
                report = f"📊 **LAPORAN HARIAN (GROQ)**\n━━━━━━━━━━━━━━\n✅ Total Trade: {total}\n🏆 Winrate: {(wins/total)*100:.1f}%\n💰 Total ROI: {total_roi:,.2f}%"
                bot.send_message(CHAT_ID, report)
                TRADE_HISTORY = [] 
            time.sleep(70) 
        time.sleep(30)

# --- UI SEND SIGNAL ---
def send_signal_ui(sig_data):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    symbol = sig_data['symbol']
    side = "🟢 LONG" if sig_data['signal'] == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    msg = (
        f"🏛️ **ICT SMC PRO SIGNAL (GROQ)**\n"
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

# --- SCANNER (Hanya Gainer & Loser, No Stablecoins) ---
def run_scanner():
    print(f"🔍 Scanning Market: {datetime.now(timezone.utc)}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    # Filter: Berakhir USDT, Bukan Stablecoin, Volume > 5M
    valid = [
        c for c in res 
        if c['symbol'].endswith("USDT") 
        and c['symbol'] not in STABLE_COINS 
        and float(c['quoteVolume']) > 5000000
    ]
    
    # Fokus Hanya pada Top 5 Gainers & Top 5 Losers
    gainers = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:5]
    losers = sorted(valid, key=lambda x: float(x['priceChangePercent']))[:5]
    
    targets = {t['symbol']: t for t in (gainers + losers)}.values()
    for t in targets:
        try:
            if any(s['symbol'] == t['symbol'] for s in ACTIVE_SIGNALS): continue
            sig = get_ai_analysis(t)
            if sig: send_signal_ui(sig)
            time.sleep(5) 
        except: continue

# --- HANDLERS (Manual Cek & Tombol) ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "🏛️ **SMC AI Bot System Aktif**\nSilahkan gunakan menu di bawah:", parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🔍 Scan Market Sekarang")
def manual_scan_btn(message):
    bot.send_message(message.chat.id, "🔄 Memulai pemindaian pasar instan...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "📊 Status Bot")
def status_btn(message):
    total_active = len(ACTIVE_SIGNALS)
    active_pairs = ", ".join([s['symbol'] for s in ACTIVE_SIGNALS]) if ACTIVE_SIGNALS else "Tidak ada"
    status_msg = f"🟢 **Bot Status: Online**\n\n🎯 Sinyal Aktif: {total_active}\n🪙 Koin dipantau: {active_pairs}"
    bot.send_message(message.chat.id, status_msg, parse_mode="Markdown")

@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.startswith('/cek'))
def manual_check(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Gunakan: `/cek BTC`", parse_mode="Markdown")
            return
            
        coin = parts[1].upper()
        symbol = f"{coin}USDT" if not coin.endswith("USDT") else coin
        
        if symbol in STABLE_COINS:
            bot.reply_to(message, "⚠️ Koin stable tidak didukung untuk analisa.")
            return

        bot.send_message(CHAT_ID, f"🔄 Menganalisis {symbol} dengan Groq AI...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        if res:
            sig = get_ai_analysis(res)
            if sig: send_signal_ui(sig)
            else: bot.send_message(CHAT_ID, f"⚠️ AI belum menemukan peluang valid di {symbol}.")
        else:
            bot.send_message(CHAT_ID, f"❌ Pair {symbol} tidak ditemukan di Binance.")
    except Exception as e:
        bot.reply_to(message, f"❌ Terjadi kesalahan: {str(e)}")

# --- MAIN ---
if __name__ == "__main__":
    print("🚀 Bot SMC Pro (Groq Edition) Starting...")
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=send_daily_report, daemon=True).start()
    
    # Jalankan polling Telegram
    bot.send_message(CHAT_ID, "🚀 **Bot SMC Pro Online**", reply_markup=main_menu())
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    
    while True:
        run_scanner()
        time.sleep(1800)