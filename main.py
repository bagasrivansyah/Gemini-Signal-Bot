import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ACTIVE_SIGNALS = []
TRADE_HISTORY = [] # Untuk menyimpan data laporan harian
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

# --- TECHNICAL ANALYSIS (MULTI-TIMEFRAME 1H & 4H) ---
def get_multi_tf_technical(symbol):
    try:
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=15")
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        
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

# --- UPDATE: AI SNIPER ENGINE (QUANT & LEARNING) ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data.get('symbol')
    price = float(coin_data.get('lastPrice') or coin_data.get('price', 0))
    
    tf_data = get_multi_tf_technical(symbol)
    if tf_data == "INSUFFICIENT" or tf_data is None: return "SKIP"

    # PROMPT TERBARU: QUANTITATIVE ANALYSIST & MACHINE LEARNING MODEL
    prompt = f"""
    Role: Senior Quantitative Analyst & Machine Learning Trading Engine.
    Object: {symbol} at {format_price(price)}.
    
    Technical Quantitative Data:
    - 4H Institutional Trend: {tf_data['trend_4h']}
    - 1H Current Price: {format_price(tf_data['price_1h'])}
    - 24h Statistical Range: {format_price(tf_data['low_24h'])} to {format_price(tf_data['high_24h'])}
    - Predictive Model: Cross-referencing 4H Trend with 1H Order Flow.

    Task:
    Jalankan algoritma Quantum Quant untuk mendeteksi market inefficiency (FVG) dan Liquidity Cluster (Order Block).
    
    Protokol Quant Wajib:
    1. Win Probability Analysis: Berikan sinyal hanya jika probabilitas keberhasilan model > 75%. Jika di bawah itu, return "WAIT".
    2. Market Phase Detection: Identifikasi fase 'Accumulation', 'Manipulation', atau 'Distribution' (AMD).
    3. Quantitative Exits: TP1, TP2, TP3 harus dihitung secara presisi berdasarkan Fibonacci Golden Ratio (0.618) atau Standard Deviation.
    4. Risk Management: Stop Loss (SL) wajib di luar cluster likuiditas. Maksimal SL 2.5%.
    5. No Scientific Notation: Tulis semua angka dalam desimal murni lengkap.

    Output RAW JSON ONLY:
    {{
        "symbol": "{symbol}",
        "signal": "LONG/SHORT/WAIT",
        "entry": {price},
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0,
        "reason": "Probability (%), Market Phase (AMD), and Statistical Inefficiency logic."
    }}
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=25
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"❌ AI Error {symbol}: {e}")
        return None

# --- UI DISPLAY (STRUKTUR ASLI + LINK TRADING VIEW + ROI) ---
def send_signal_ui(sig_data, target_chat):
    if not sig_data or sig_data == "SKIP": return
    
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal', 'WAIT')).upper()
    entry = sig_data.get('entry', 0)
    tp1, tp2, tp3 = sig_data.get('tp1', 0), sig_data.get('tp2', 0), sig_data.get('tp3', 0)
    sl = sig_data.get('sl', 0)

    if not symbol or side not in ['LONG', 'SHORT'] or entry == 0: return

    roi1, roi2, roi3 = calculate_roi(entry, tp1, side), calculate_roi(entry, tp2, side), calculate_roi(entry, tp3, side)
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

    msg = (
        f"🏛️ **SNIPER SMC PRO SIGNAL**\n"
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
        f"💡 **AI Logic:** {sig_data.get('reason', 'Analysis Done')}\n\n"
        f"📊 [Buka Chart TradingView]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Sniper Dev: Bagas Rivansyah*"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)
    
    if not any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS):
        ACTIVE_SIGNALS.append(sig_data)

# --- HANDLER MANUAL CEK (RESPONSIF) ---
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
        if symbol in STABLE_COINS: return

        sent_msg = bot.send_message(uid, f"🔍 Sniper AI sedang menganalisis **{symbol}**...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        
        if res:
            sig = get_ai_analysis(res)
            if sig == "SKIP":
                bot.edit_message_text(f"⚠️ **{symbol}**: Data tidak cukup.", uid, sent_msg.message_id)
            elif sig:
                if str(sig.get('signal', 'WAIT')).upper() == "WAIT":
                    bot.edit_message_text(f"☕ **{symbol}**: AI menyarankan **WAIT**.", uid, sent_msg.message_id)
                else:
                    bot.delete_message(uid, sent_msg.message_id)
                    send_signal_ui(sig, uid)
            else:
                bot.edit_message_text(f"❌ Groq AI sedang sibuk.", uid, sent_msg.message_id)
        else:
            bot.edit_message_text(f"❌ **{symbol}** tidak ditemukan.", uid, sent_msg.message_id)
    except: pass

# --- MONITORING HARGA + HISTORY UNTUK LAPORAN ---
def monitor_active_signals():
    global TRADE_HISTORY
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol = sig.get('symbol')
                entry, side = float(sig.get('entry', 0)), str(sig.get('signal')).upper()
                sl, tp3 = float(sig.get('sl', 0)), float(sig.get('tp3', 0))
                
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr = float(res['price'])
                
                is_hit, status = False, ""
                if (side == "LONG" and curr <= sl) or (side == "SHORT" and curr >= sl):
                    roi, status, is_hit = -100.0, "🛑 STOP LOSS HIT", True
                elif (side == "LONG" and curr >= tp3) or (side == "SHORT" and curr <= tp3):
                    roi, status, is_hit = calculate_roi(entry, curr, side), "🎯 TAKE PROFIT HIT", True

                if is_hit:
                    msg = f"{status}\n━━━━━━━━━━━━━━\n🪙 #{symbol}\n📈 ROI: {roi:+.1f}%\n💵 Exit: {format_price(curr)}"
                    bot.send_message(CHAT_ID, msg)
                    TRADE_HISTORY.append({"symbol": symbol, "roi": roi, "status": status})
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=4)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

# --- MESIN LAPORAN HARIAN ---
def daily_report_scheduler():
    global TRADE_HISTORY
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute == 0:
            if TRADE_HISTORY:
                total_trades = len(TRADE_HISTORY)
                wins = len([t for t in TRADE_HISTORY if t['roi'] > 0])
                total_roi = sum([t['roi'] for t in TRADE_HISTORY])
                winrate = (wins / total_trades) * 100
                
                report = (
                    f"📊 **LAPORAN HARIAN SNIPER AI**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Total Sinyal Selesai: {total_trades}\n"
                    f"🏆 Win Rate: {winrate:.1f}%\n"
                    f"💰 Akumulasi ROI: {total_roi:+.2f}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Semoga hari ini lebih cuan!"
                )
                bot.send_message(CHAT_ID, report, parse_mode="Markdown")
                TRADE_HISTORY = [] 
            time.sleep(70)
        time.sleep(30)

# --- SCANNER OTOMATIS (GAINER, LOSER, TRENDING) ---
def run_scanner():
    global COOLDOWN_COINS
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    
    targets = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:4] + \
              sorted(valid, key=lambda x: float(x['priceChangePercent']))[:4] + \
              sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:2]
    
    target_dict = {t['symbol']: t for t in targets}
    for t in target_dict.values():
        if any(s.get('symbol') == t['symbol'] for s in ACTIVE_SIGNALS) or t['symbol'] in COOLDOWN_COINS: continue
        sig = get_ai_analysis(t)
        if sig and sig != "SKIP":
            send_signal_ui(sig, CHAT_ID)
            time.sleep(15) 

# --- HANDLERS UTAMA ---
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
    bot.send_message(message.chat.id, f"🟢 **Bot Online**\n🎯 Signals Monitored: {total}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=daily_report_scheduler, daemon=True).start()
    
    def scanner_scheduler():
        while True:
            run_scanner()
            time.sleep(1800)
    threading.Thread(target=scanner_scheduler, daemon=True).start()
    
    print("🚀 Sniper Bot is Polling...")
    bot.infinity_polling(skip_pending=True)