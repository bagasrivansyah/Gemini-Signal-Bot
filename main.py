import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
COOLDOWN_COINS = {} # Untuk mencatat kapan koin terakhir selesai trade
LEVERAGE = 20

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "PAXGUSDT", "USDTUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- HELPER: HITUNG ROI ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        if side.upper() == "LONG":
            diff = target - entry
        else:
            diff = entry - target
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

def call_binance_api(endpoint):
    endpoints = ["https://api.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]
    for base_url in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

# --- TEKNIKAL ICT SMC (DATA PENDUKUNG AI) ---
def get_ict_technical(symbol):
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        if not data or len(data) < 20: return None
        c = [{"h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "v": float(x[5])} for x in data]
        price = c[-1]['c']
        # Deteksi sederhana FVG/Orderblock untuk referensi AI
        avg_vol = sum([x['v'] for x in c[-10:]]) / 10
        bias = "NEUTRAL"
        if c[-2]['v'] > (avg_vol * 1.3):
            if c[-2]['c'] > c[-2]['o']: bias = "BULLISH IMPULSE"
            else: bias = "BEARISH IMPULSE"
        return {"bias": bias, "price": price, "high_24h": max([x['h'] for x in c]), "low_24h": min([x['l'] for x in c])}
    except: return None

# --- SNIPER AI ANALYSIS ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data['symbol']
    price = float(coin_data.get('lastPrice') or coin_data.get('price'))
    change = coin_data.get('priceChangePercent', '0')
    ict = get_ict_technical(symbol)
    
    # Prompt yang lebih "Sniper" dan Profesional
    prompt = f"""
    Role: Senior Institutional Trader (SMC/ICT Expert). Winrate 90%.
    Market: {symbol} at {format_price(price)} ({change}% 24h).
    Technical Data: {ict if ict else 'Check price action'}.

    Task: Cari 'Sniper Entry' berdasarkan Liquidity Sweep, BOS (Break of Structure), atau CHoCH.
    PENTING:
    1. Jika tidak ada setup jelas, berikan signal "WAIT".
    2. TP/SL harus RASIONAL. Risk:Reward minimal 1:2. 
    3. Stop Loss jangan terlalu jauh (Maksimal 1-3% dari harga entry).
    4. Dilarang keras menggunakan scientific notation.

    Output RAW JSON ONLY:
    {{
        "symbol": "{symbol}",
        "signal": "LONG/SHORT/WAIT",
        "entry": {price},
        "tp1": 0.0, "tp2": 0.0, "tp3": 0.0, "sl": 0.0,
        "reason": "Detail alasan SMC (Liquidity/Orderblock/BOS)"
    }}
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- MONITORING DENGAN COOLDOWN ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, TRADE_HISTORY, COOLDOWN_COINS
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
                status = ""
                # Cek SL
                if (side == "LONG" and curr_price <= float(sig['sl'])) or (side == "SHORT" and curr_price >= float(sig['sl'])):
                    status = "🛑 SL HIT"
                    is_hit = True
                # Cek TP3 (Final)
                elif (side == "LONG" and curr_price >= float(sig['tp3'])) or (side == "SHORT" and curr_price <= float(sig['tp3'])):
                    status = "🎯 TP3 HIT (MAX)"
                    is_hit = True

                if is_hit:
                    roi = calculate_roi(entry, curr_price, side)
                    msg = f"{status}\n━━━━━━━━━━━━━━\n🪙 #{symbol}\n📈 ROI: {roi:,.2f}%\n💵 Exit: {format_price(curr_price)}"
                    bot.send_message(CHAT_ID, msg)
                    
                    # Tambahkan COOLDOWN (1 jam) agar koin ini tidak langsung muncul lagi
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=1)
                    
                    TRADE_HISTORY.append({"symbol": symbol, "roi": roi, "time": datetime.now(timezone.utc)})
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

# --- UI SEND SIGNAL DENGAN ROI ---
def send_signal_ui(sig_data):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    symbol = sig_data['symbol']
    side = sig_data['signal'].upper()
    entry = sig_data['entry']
    
    # Hitung ROI untuk setiap target
    roi1 = calculate_roi(entry, sig_data['tp1'], side)
    roi2 = calculate_roi(entry, sig_data['tp2'], side)
    roi3 = calculate_roi(entry, sig_data['tp3'], side)
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    msg = (
        f"🏛️ **SNIPER SMC SIGNAL**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `{LEVERAGE}x`\n"
        f"📈 **Side:** {side_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{format_price(entry)}`\n\n"
        f"🎯 **TP1:** `{format_price(sig_data['tp1'])}` ({roi1:+.1f}%)\n"
        f"🎯 **TP2:** `{format_price(sig_data['tp2'])}` ({roi2:+.1f}%)\n"
        f"🎯 **TP3:** `{format_price(sig_data['tp3'])}` ({roi3:+.1f}%)\n"
        f"🛑 **SL:** `{format_price(sig_data['sl'])}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI:** {sig_data.get('reason', 'High probability setup')}\n\n"
        f"📊 [Lihat Chart TradingView]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Sniper Dev: Bagas Rivansyah*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)
    ACTIVE_SIGNALS.append(sig_data) 

# --- SCANNER: TRENDING, GAINER, LOSER ---
def run_scanner():
    global COOLDOWN_COINS
    print(f"🔍 Sniper Scan: {datetime.now(timezone.utc)}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    now = datetime.now(timezone.utc)
    # Bersihkan cooldown koin yang sudah lewat waktunya
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}

    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    
    # Ambil Gainer, Loser, dan Trending (Volume)
    gainers = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:5]
    losers = sorted(valid, key=lambda x: float(x['priceChangePercent']))[:5]
    trending = sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:5]
    
    targets = {t['symbol']: t for t in (gainers + losers + trending)}.values()
    
    for t in targets:
        symbol = t['symbol']
        try:
            # Lewati jika sedang aktif atau masih dalam cooldown
            if any(s['symbol'] == symbol for s in ACTIVE_SIGNALS): continue
            if symbol in COOLDOWN_COINS: continue
            
            sig = get_ai_analysis(t)
            if sig:
                send_signal_ui(sig)
                time.sleep(12) 
        except: continue

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "🚀 **Sniper SMC Pro Online**\nMode: Smart Scanner Enabled", reply_markup=main_menu())

def main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🔍 Scan Market Sekarang"), KeyboardButton("📊 Status Bot"))
    return markup

@bot.message_handler(func=lambda m: m.text == "🔍 Scan Market Sekarang")
def manual_scan(message):
    bot.reply_to(message, "🔄 Sniper sedang membidik market...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "📊 Status Bot")
def status_btn(message):
    total = len(ACTIVE_SIGNALS)
    pairs = ", ".join([s['symbol'] for s in ACTIVE_SIGNALS]) if ACTIVE_SIGNALS else "None"
    bot.send_message(message.chat.id, f"🟢 **Status: Sniper Active**\n🎯 Signals: {total}\n🪙 Monitoring: {pairs}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    while True:
        run_scanner()
        time.sleep(1800)