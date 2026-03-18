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

# === CONFIGURATION (Railway Variables) ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN TELEGRAM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")

try:
    if not GEMINI_API_KEY:
        print("❌ ERROR: GEMINI_API_KEY tidak ditemukan!")
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("✅ Gemini AI Terhubung (Mode Scalping Agresif).")
except Exception as e:
    print(f"❌ Gagal Inisialisasi AI: {e}")

if not TOKEN_TELEGRAM:
    print("❌ ERROR: TOKEN_TELEGRAM tidak ditemukan!")
    exit()

bot = telebot.TeleBot(TOKEN_TELEGRAM)
BINANCE_URLS = ["https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]
active_signals = []

def call_binance_api(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            continue
    return None

def get_technical_data(symbol):
    try:
        # Ambil data dari 3 timeframe
        d15m = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=15m&limit=50")
        d1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        d4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=50")
        
        if not d15m or not d1h or not d4h: return None
        
        # DataFrame 15m (Titik Eksekusi)
        df15 = pd.DataFrame(d15m, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df15['close'] = df15['c'].astype(float)
        df15['ema_9'] = ta.ema(df15['close'], length=9)
        df15['ema_21'] = ta.ema(df15['close'], length=21)
        
        # Data Konfirmasi (1h & 4h)
        ema21_1h = ta.ema(pd.Series([float(x[4]) for x in d1h]), length=21).iloc[-1]
        ema21_4h = ta.ema(pd.Series([float(x[4]) for x in d4h]), length=21).iloc[-1]
        
        current_price = df15['close'].iloc[-1]
        
        # LOGIKA LEBIH AGRESIF: Sinyal muncul jika 1H & 15M searah (4H hanya sebagai informasi tambahan)
        is_bullish = (current_price > ema21_1h and df15['ema_9'].iloc[-1] > df15['ema_21'].iloc[-1])
        is_bearish = (current_price < ema21_1h and df15['ema_9'].iloc[-1] < df15['ema_21'].iloc[-1])
        
        trend = "UP" if is_bullish else "DOWN" if is_bearish else "SIDELINES"
        
        # Volume Spike: Gunakan rata-rata 15m untuk deteksi cepat
        avg_vol = df15['v'].astype(float).iloc[-21:-1].mean()
        vol_ratio = round(df15['v'].astype(float).iloc[-1] / avg_vol, 2)
        
        return {
            "trend": trend, 
            "price": current_price, 
            "vol_spike": f"{vol_ratio}x",
            "big_trend": "BULL" if current_price > ema21_4h else "BEAR"
        }
    except:
        return None

def get_ai_analysis(coin):
    tech = get_technical_data(coin['symbol'])
    # Bot akan mengirim ke AI jika minimal 1H & 15M sudah searah
    if not tech or tech['trend'] == "SIDELINES": return None
    
    prompt = f"""
    Act as an expert Scalper. Analyze {coin['symbol']}.
    Current Price: {tech['price']}, Local Trend (1H/15M): {tech['trend']}, Global Trend (4H): {tech['big_trend']}.
    Vol Spike 15m: {tech['vol_spike']}.
    Requirement: Give 20x Leverage Scalping Signal. Target quick 10-30% profit.
    Output MUST be raw JSON:
    {{"symbol": "{coin['symbol']}", "signal": "{'LONG' if tech['trend'] == 'UP' else 'SHORT'}", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "data_info": "{tech['vol_spike']} (Fast Scalp)", "reason": "1H/15M Alignment with {tech['vol_spike']} volume spike."}}
    """
    
    try:
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        clean_json = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(clean_json)
    except:
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    
    msg = (
        f"🔥 **FAST SCALPING SIGNAL** 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol}\n"
        f"📈 **Type:** {sig_data['signal']} | 20x (Cross)\n"
        f"📊 **Vol Spike:** {sig_data.get('data_info', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Entry:** {sig_data['entry']}\n\n"
        f"✅ **Target Profit:**\n"
        f"  └ TP1: {sig_data['tp1']}\n"
        f"  └ TP2: {sig_data['tp2']}\n"
        f"  └ TP3: {sig_data['tp3']}\n\n"
        f"🛑 **Stop Loss:** {sig_data['sl']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [LIHAT CHART]({chart_url})\n"
        f"⚠️ *Bagas Rivansyah: Scalping Cepat!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def check_monitoring():
    global active_signals
    if not active_signals: return
    try:
        prices = call_binance_api("/api/v3/ticker/price")
        if not prices: return
        price_map = {p['symbol']: float(p['price']) for p in prices}
        
        for sig in active_signals[:]:
            cp = price_map.get(sig['symbol'])
            if not cp: continue
            
            is_long = sig['signal'].upper() == "LONG"
            if (is_long and cp <= sig['sl']) or (not is_long and cp >= sig['sl']):
                bot.send_message(CHAT_ID, f"❌ **#{sig['symbol']} SL HIT!**")
                active_signals.remove(sig)
                continue
            
            for i in range(1, 4):
                tp_key = f'tp{i}'
                hit_key = f'hit_tp{i}'
                if hit_key not in sig:
                    is_hit = (cp >= sig[tp_key]) if is_long else (cp <= sig[tp_key])
                    if is_hit:
                        bot.send_message(CHAT_ID, f"✅ **#{sig['symbol']} TP{i} HIT!** 🚀")
                        sig[hit_key] = True
                        if i == 3: active_signals.remove(sig)
    except: pass

def run_scanner():
    print("🔍 Gemini Scanning Market (Fast Mode)...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        # TURUNKAN FILTER VOLUME KE 50.000 agar bot lebih aktif mencari koin
        targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 50000]
        targets = sorted(targets, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)[:20]
        
        found = False
        for t in targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
                time.sleep(1) # Delay kecil agar tidak kena rate limit
        
        if not found:
            bot.send_message(CHAT_ID, "🔍 Scan selesai: Market sangat tenang (Belum ada momentum).")
    except Exception as e:
        print(f"Scanner Error: {e}")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Gemini AI sedang mencari momentum scalping cepat...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    msg = (f"🤖 **Status Bot:** Aktif (Fast Scalp Mode)\n"
           f"📈 Sinyal Aktif: {len(active_signals)}\n"
           f"🎯 Strategi: 1H & 15M Trend Alignment\n"
           f"👤 Developer: Bagas Rivansyah")
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    print("🚀 Bot Starting...")
    try:
        bot.send_message(CHAT_ID, f"🚀 **Bot Gemini Bagas Rivansyah Online!**", reply_markup=main_keyboard())
    except Exception as e:
        print(f"Gagal kirim pesan start: {e}")
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    last_scan = 0
    while True:
        # Scan otomatis lebih sering (setiap 10 menit) agar tidak ketinggalan momentum
        if time.time() - last_scan > 600: 
            run_scanner()
            last_scan = time.time()
        # Cek TP/SL setiap 10 detik agar notifikasi cepat
        check_monitoring()
        time.sleep(10)
