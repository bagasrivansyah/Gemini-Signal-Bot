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

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- HELPER: HITUNG ROI ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        diff = (target - entry) if side.upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

# --- HELPER: FORMAT HARGA (PRESISI TINGGI UNTUK MICIN) ---
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
        # Tambahkan timeout agar tidak hang jika jaringan lambat
        response = requests.get(url, timeout=10) 
        if response.status_code == 200: return response.json()
    except: return None
    return None

# --- TECHNICAL ANALYSIS (FIXED INDEX & SPEED) ---
def get_multi_tf_technical(symbol):
    try:
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=10")
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        
        # Validasi minimal data (minimal 6 candle untuk perbandingan index -5)
        if not data_4h or len(data_4h) < 6 or not data_1h or len(data_1h) < 2:
            return None

        c4h = [{"c": float(x[4])} for x in data_4h]
        trend_4h = "BULLISH" if c4h[-1]['c'] > c4h[-5]['c'] else "BEARISH"
        
        c1h = [{"c": float(x[4]), "h": float(x[2]), "l": float(x[3])} for x in data_1h]
        price_now = c1h[-1]['c']
        
        vol_change = abs(c1h[-1]['c'] - c1h[-2]['c'])
        volatility = "HIGH" if vol_change > (price_now * 0.005) else "NORMAL"
        
        return {
            "trend_4h": trend_4h,
            "price_1h": price_now,
            "high_24h": max([x['h'] for x in c1h]),
            "low_24h": min([x['l'] for x in c1h]),
            "volatility": volatility
        }
    except:
        return None

# --- AI SNIPER ENGINE ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data['symbol']
    price = float(coin_data.get('lastPrice') or coin_data.get('price'))
    tf_data = get_multi_tf_technical(symbol)
    
    # Jika data teknikal tidak cukup, segera kembalikan None agar scanner tidak sleep
    if not tf_data:
        return None

    prompt = f"""
    Role: Senior Institutional Trader. Analisa {symbol} price {format_price(price)}.
    4H Trend: {tf_data['trend_4h']}. Volatility: {tf_data['volatility']}.
    Task: Berikan Sniper Signal JSON: signal(LONG/SHORT/WAIT), entry, tp1, tp2, tp3, sl, reason.
    Ketentuan: Searah trend 4H, RR 1:2, SL max 3%, NO scientific notation.
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=20
        )
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- UI DISPLAY ---
def send_signal_ui(sig_data, target_chat=CHAT_ID):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    symbol, side, entry = sig_data['symbol'], sig_data['signal'].upper(), float(sig_data['entry'])
    
    roi1 = calculate_roi(entry, sig_data['tp1'], side)
    roi2 = calculate_roi(entry, sig_data['tp2'], side)
    roi3 = calculate_roi(entry, sig_data['tp3'], side)
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    msg = (
        f"🏛️ **MULTI-TF SNIPER SIGNAL**\n"
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
        f"💡 **AI:** {sig_data.get('reason', 'Institutional Alignment OK')}\n\n"
        f"📊 [Lihat Chart TradingView]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Sniper Dev: Bagas Rivansyah*"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)
    ACTIVE_SIGNALS.append(sig_data) 

# --- MANUAL CHECK HANDLER (FAST RESPON) ---
@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.lower().startswith('cek'))
def manual_check(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "💡 Format: `/cek BTC`", parse_mode="Markdown")
            return
            
        coin = parts[1].upper().replace("USDT", "")
        symbol = f"{coin}USDT"
        
        if symbol in STABLE_COINS:
            bot.reply_to(message, "⚠️ Koin stable diabaikan.")
            return

        sent_msg = bot.send_message(message.chat.id, f"🔍 Menganalisis **{symbol}**...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        
        if res and 'lastPrice' in res:
            sig = get_ai_analysis(res)
            if sig:
                if sig.get('signal') == "WAIT":
                    bot.edit_message_text(f"☕ **{symbol}**: AI menyarankan **WAIT**. Belum ada setup sniper.", message.chat.id, sent_msg.message_id)
                else:
                    bot.delete_message(message.chat.id, sent_msg.message_id)
                    send_signal_ui(sig, message.chat.id)
            else:
                bot.edit_message_text(f"⚠️ **{symbol}**: Data history tidak cukup atau AI sibuk.", message.chat.id, sent_msg.message_id)
        else:
            bot.edit_message_text(f"❌ Pair **{symbol}** tidak ditemukan di Binance Spot.", message.chat.id, sent_msg.message_id)
    except: pass

# --- MONITORING ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, COOLDOWN_COINS
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol, entry, side = sig['symbol'], float(sig['entry']), sig['signal'].upper()
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr_price = float(res['price'])
                
                is_hit = False
                if (side == "LONG" and curr_price <= float(sig['sl'])) or (side == "SHORT" and curr_price >= float(sig['sl'])):
                    bot.send_message(CHAT_ID, f"🛑 **SL HIT**\n#{symbol}\nPrice: {format_price(curr_price)}")
                    is_hit = True
                elif (side == "LONG" and curr_price >= float(sig['tp3'])) or (side == "SHORT" and curr_price <= float(sig['tp3'])):
                    bot.send_message(CHAT_ID, f"🎯 **TP3 HIT**\n#{symbol}\nROI: {calculate_roi(entry, curr_price, side):.1f}%")
                    is_hit = True

                if is_hit:
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=1)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

# --- SCANNER (SPEED OPTIMIZED) ---
def run_scanner():
    global COOLDOWN_COINS
    print(f"🔍 Multi-TF Sniper Scan: {datetime.now(timezone.utc)}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    
    targets = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:5] + \
              sorted(valid, key=lambda x: float(x['priceChangePercent']))[:5]
    
    for t in targets:
        symbol = t['symbol']
        try:
            if any(s['symbol'] == symbol for s in ACTIVE_SIGNALS) or symbol in COOLDOWN_COINS: continue
            
            sig = get_ai_analysis(t)
            
            # Jika AI berhasil memberikan sinyal (bukan None karena kurang data)
            if sig:
                send_signal_ui(sig, CHAT_ID)
                # Hanya beri jeda jika benar-benar mengirim sinyal untuk menjaga Rate Limit AI
                time.sleep(15) 
            # Jika sig adalah None, loop akan langsung lanjut ke koin berikutnya tanpa menunggu
        except: continue

# --- MAIN ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🔍 Scan Market Sekarang"), KeyboardButton("📊 Status Bot"))
    bot.send_message(message.chat.id, "🚀 **Multi-TF Sniper Online**", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🔍 Scan Market Sekarang")
def manual_scan_btn(message):
    bot.reply_to(message, "🔄 Menjalankan Sniper Scan...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "📊 Status Bot")
def status_btn(message):
    total = len(ACTIVE_SIGNALS)
    bot.send_message(message.chat.id, f"🟢 **Bot Online**\n🎯 Signals: {total}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    while True:
        run_scanner()
        time.sleep(1800)