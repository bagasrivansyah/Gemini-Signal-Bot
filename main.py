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
    print("✅ Gemini AI Terhubung (Mode Multi-Timeframe).")
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
        # Ambil data dari 3 timeframe untuk akurasi scalping
        d15m = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=15m&limit=50")
        d1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        d4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=50")
        
        if not d15m or not d1h or not d4h: return None
        
        # Proses DataFrame 15m (Titik Eksekusi)
        df15 = pd.DataFrame(d15m, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df15['close'] = df15['c'].astype(float)
        df15['ema_9'] = ta.ema(df15['close'], length=9)
        df15['ema_21'] = ta.ema(df15['close'], length=21)
        
        # Proses Data Konfirmasi (1h & 4h)
        c1h = float(d1h[-1][4]) # Close price 1h
        ema21_1h = ta.ema(pd.Series([float(x[4]) for x in d1h]), length=21).iloc[-1]
        
        c4h = float(d4h[-1][4]) # Close price 4h
        ema21_4h = ta.ema(pd.Series([float(x[4]) for x in d4h]), length=21).iloc[-1]
        
        current_price = df15['close'].iloc[-1]
        
        # Logika Tren Multi-Timeframe (Konfirmasi searah)
        is_bullish = (current_price > ema21_4h and current_price > ema21_1h and df15['ema_9'].iloc[-1] > df15['ema_21'].iloc[-1])
        is_bearish = (current_price < ema21_4h and current_price < ema21_1h and df15['ema_9'].iloc[-1] < df15['ema_21'].iloc[-1])
        
        trend = "UP" if is_bullish else "DOWN" if is_bearish else "SIDELINES"
        
        avg_vol = df15['v'].astype(float).iloc[-21:-1].mean()
        vol_ratio = round(df15['v'].astype(float).iloc[-1] / avg_vol, 2)
        
        return {
            "trend": trend, 
            "price": current_price, 
            "vol_spike": f"{vol_ratio}x",
            "tf_status": "MTF 4H-1H-15M Aligned" if trend != "SIDELINES" else "Mixed"
        }
    except:
        return None

def get_ai_analysis(coin):
    tech = get_technical_data(coin['symbol'])
    if not tech or tech['trend'] == "SIDELINES": return None
    
    prompt = f"""
    Act as an expert Scalper. Analyze {coin['symbol']}.
    Price: {tech['price']}, Trend: {tech['trend']} (4H-1H-15M Confirmed), Vol Spike: {tech['vol_spike']}.
    Requirement: 20x Leverage Signal. 
    Output MUST be raw JSON:
    {{"symbol": "{coin['symbol']}", "signal": "{'LONG' if tech['trend'] == 'UP' else 'SHORT'}", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "data_info": "{tech['vol_spike']} (Scalp)", "reason": "Expert tech reason based on MTF alignment"}}
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
        f"🔥 **NEW SCALPING SIGNAL** 🔥\n"
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
        f"⚠️ *Bagas Rivansyah: Gunakan RM!*"
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
    print("🔍 Gemini Scanning Market (Scalping Mode)...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 100000]
        targets = sorted(targets, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)[:15]
        
        found = False
        for t in targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
                time.sleep(1)
        
        if not found:
            bot.send_message(CHAT_ID, "🔍 Scan selesai: Tidak ada momentum MTF yang searah.")
    except Exception as e:
        print(f"Scanner Error: {e}")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Gemini AI sedang memindai momentum scalping...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    msg = (f"🤖 **Status Bot:** Aktif (Scalping Mode)\n"
           f"📈 Sinyal Aktif: {len(active_signals)}\n"
           f"🎯 Strategi: MTF (4H-1H-15M) Alignment\n"
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
        if time.time() - last_scan > 900: # Scan otomatis setiap 15 menit
            run_scanner()
            last_scan = time.time()
        check_monitoring()
        time.sleep(30)
