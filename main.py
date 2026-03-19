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
COOLDOWN_COINS = {} 
LEVERAGE = 20

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "PAXGUSDT", "USDTUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

# TETAPKAN STRUKTUR BOT ASLI
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=15)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- HELPER: HITUNG ROI ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        if entry == 0: return 0
        diff = (target - entry) if str(side).upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

# --- HELPER: FORMAT HARGA (PRESISI MICIN) ---
def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.0001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

def call_binance_api(endpoint):
    url = f"https://api.binance.com{endpoint}"
    try:
        response = requests.get(url, timeout=10) 
        if response.status_code == 200: return response.json()
    except: return None
    return None

# --- TECHNICAL ANALYSIS (FIXED INDEX ERROR) ---
def get_multi_tf_technical(symbol):
    try:
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=15")
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        
        # Validasi panjang data agar tidak Error Out of Range
        if not data_4h or len(data_4h) < 6 or not data_1h or len(data_1h) < 2:
            return "INSUFFICIENT"

        c4h = [{"c": float(x[4])} for x in data_4h]
        trend_4h = "BULLISH" if c4h[-1]['c'] > c4h[-5]['c'] else "BEARISH"
        
        c1h = [{"c": float(x[4]), "h": float(x[2]), "l": float(x[3])} for x in data_1h]
        return {
            "trend_4h": trend_4h,
            "price_1h": c1h[-1]['c'],
            "high_24h": max([x['h'] for x in c1h]),
            "low_24h": min([x['l'] for x in c1h])
        }
    except: return None

# --- AI SNIPER ENGINE ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data.get('symbol')
    price = float(coin_data.get('lastPrice') or coin_data.get('price', 0))
    
    tf_data = get_multi_tf_technical(symbol)
    if tf_data == "INSUFFICIENT" or tf_data is None: return "SKIP"

    prompt = f"Expert Institutional SMC Trader. Analisa {symbol} price {format_price(price)}. 4H Trend: {tf_data['trend_4h']}. Berikan Sniper Signal JSON: symbol, signal(LONG/SHORT/WAIT), entry, tp1, tp2, tp3, sl, reason. RR 1:2. No scientific notation."
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=20
        )
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- UI DISPLAY (STRUKTUR ASLI + LINK TRADING VIEW) ---
def send_signal_ui(sig_data, target_chat):
    if not sig_data or sig_data == "SKIP": return
    
    # Validasi Kunci JSON agar tidak KeyError
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal', 'WAIT')).upper()
    entry = sig_data.get('entry')
    tp1 = sig_data.get('tp1')
    tp2 = sig_data.get('tp2')
    tp3 = sig_data.get('tp3')
    sl = sig_data.get('sl')

    if not all([symbol, side, entry, tp1, sl]) or side not in ['LONG', 'SHORT']:
        return

    # ROI Calculation
    roi1 = calculate_roi(entry, tp1, side)
    roi2 = calculate_roi(entry, tp2, side)
    roi3 = calculate_roi(entry, tp3, side)
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

    # KEMBALIKAN FORMAT PESAN ASLI ANDA
    msg = (
        f"🏛️ **MULTI-TF SNIPER SIGNAL**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `{LEVERAGE}x`\n"
        f"📈 **Side:** {side_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{format_price(entry)}`\n\n"
        f"🎯 **TP1:** `{format_price(tp1)}` ({roi1:+.1f}%)\n"
        f"🎯 **TP2:** `{format_price(tp2)}` ({roi2:+.1f}%)\n"
        f"🎯 **TP3:** `{format_price(tp3)}` ({roi3:+.1f}%)\n"
        f"🛑 **SL:** `{format_price(sl)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI:** {sig_data.get('reason', 'Analysis Done')}\n\n"
        f"📊 [Buka Chart TradingView]({tv_link})\n" # LINK TRADING VIEW KEMBALI
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Sniper Dev: Bagas Rivansyah*"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)
    
    if not any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS):
        ACTIVE_SIGNALS.append(sig_data)

# --- HANDLER MANUAL CEK (DIPERBAIKI AGAR RESPONSIF) ---
@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.lower().startswith('cek'))
def manual_check(message):
    uid = message.chat.id
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "💡 Format: `/cek BTC`", parse_mode="Markdown")
            return
            
        coin = "".join(re.findall(r'[A-Z0-9]', parts[1].upper()))
        symbol = f"{coin}USDT" if not coin.endswith("USDT") else coin
        
        if symbol in STABLE_COINS:
            bot.reply_to(message, "⚠️ Koin stable diabaikan.")
            return

        sent_msg = bot.send_message(uid, f"🔍 Menganalisis **{symbol}**...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        
        if res:
            sig = get_ai_analysis(res)
            if sig == "SKIP":
                bot.edit_message_text(f"⚠️ **{symbol}**: Data history tidak cukup.", uid, sent_msg.message_id)
            elif sig:
                if str(sig.get('signal', 'WAIT')).upper() == "WAIT":
                    bot.edit_message_text(f"☕ **{symbol}**: AI menyarankan **WAIT**.", uid, sent_msg.message_id)
                else:
                    bot.delete_message(uid, sent_msg.message_id)
                    send_signal_ui(sig, uid)
            else:
                bot.edit_message_text(f"❌ AI Groq sedang sibuk.", uid, sent_msg.message_id)
        else:
            bot.edit_message_text(f"❌ **{symbol}** tidak ditemukan di Binance Spot.", uid, sent_msg.message_id)
    except: pass

# --- MONITORING HARGA (TETAP SAMA) ---
def monitor_active_signals():
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol = sig.get('symbol')
                entry = float(sig.get('entry', 0))
                side = str(sig.get('signal')).upper()
                sl = float(sig.get('sl', 0))
                tp3 = float(sig.get('tp3', 0))
                
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr = float(res['price'])
                
                is_hit = False
                if (side == "LONG" and curr <= sl) or (side == "SHORT" and curr >= sl):
                    bot.send_message(CHAT_ID, f"🛑 **SL HIT**\n#{symbol}\nPrice: {format_price(curr)}")
                    is_hit = True
                elif (side == "LONG" and curr >= tp3) or (side == "SHORT" and curr <= tp3):
                    bot.send_message(CHAT_ID, f"🎯 **TP3 HIT**\n#{symbol}\nROI: {calculate_roi(entry, curr, side):+.1f}%")
                    is_hit = True

                if is_hit:
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=1)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

# --- SCANNER OTOMATIS (TETAP SAMA) ---
def run_scanner():
    global COOLDOWN_COINS
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    
    targets = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:4] + \
              sorted(valid, key=lambda x: float(x['priceChangePercent']))[:4]
    
    for t in targets:
        symbol = t['symbol']
        if any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS) or symbol in COOLDOWN_COINS: continue
        sig = get_ai_analysis(t)
        if sig and sig != "SKIP":
            send_signal_ui(sig, CHAT_ID)
            time.sleep(15) 

# --- HANDLERS (START & STATUS) ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🔍 Scan Market Sekarang"), KeyboardButton("📊 Status Bot"))
    bot.send_message(message.chat.id, "🚀 **Sniper SMC Pro Online**", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🔍 Scan Market Sekarang")
def manual_scan_btn(message):
    bot.reply_to(message, "🔄 Menjalankan scanner asinkron...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "📊 Status Bot")
def status_btn(message):
    total = len(ACTIVE_SIGNALS)
    bot.send_message(message.chat.id, f"🟢 **Bot Online**\n🎯 Signals monitored: {total}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    def scanner_scheduler():
        while True:
            run_scanner()
            time.sleep(1800)
    threading.Thread(target=scanner_scheduler, daemon=True).start()
    
    print("🚀 Bot is polling...")
    bot.infinity_polling(skip_pending=True)