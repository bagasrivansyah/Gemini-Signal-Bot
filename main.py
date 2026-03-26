import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 8080))

# --- KEAMANAN: WHITELIST SYSTEM (OS VAR) ---
RAW_WHITELIST = os.getenv("WHITELIST_IDS", "")
WHITELIST_IDS = [int(i.strip()) for i in RAW_WHITELIST.split(",") if i.strip().isdigit()]

ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
COOLDOWN_COINS = {} 
LEVERAGE = 20

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "USD1USDT", "USDTUSDT", "UUSDT", "RLUSDUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=15)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
app = Flask(__name__)

# --- DASHBOARD HTML (ULTRA-LUXURY WITH LIVE HIT TRACKER & DUAL ALERTS) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>NEXUS QUANTUM</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=JetBrains+Mono&display=swap');
        
        body { 
            background-color: #000; 
            color: #00ff88; 
            font-family: 'JetBrains Mono', monospace; 
            margin: 0; padding: 0;
            overflow-x: hidden;
            background-image: radial-gradient(circle at 50% 50%, #0a2a1a 0%, #000 100%);
        }

        /* Scanline Effect */
        body::before {
            content: " ";
            display: block;
            position: fixed;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
            z-index: 9999;
            width: 100%; height: 100%;
            background-size: 100% 2px, 3px 100%;
            pointer-events: none;
        }

        .app-container { padding: 20px; max-width: 500px; margin: auto; }

        .app-header {
            text-align: center;
            padding: 20px 0;
            border-bottom: 1px solid #00ff88;
            margin-bottom: 25px;
        }

        .app-header h1 {
            font-family: 'Orbitron', sans-serif;
            font-size: 20px;
            margin: 0;
            letter-spacing: 5px;
            text-shadow: 0 0 10px #00ff88;
        }

        .status-bar {
            font-size: 10px;
            color: #888;
            margin-top: 5px;
            display: flex;
            justify-content: center;
            gap: 15px;
        }

        .pulse {
            width: 8px; height: 8px;
            background: #00ff88;
            border-radius: 50%;
            display: inline-block;
            animation: pulse-animation 2s infinite;
        }

        @keyframes pulse-animation {
            0% { box-shadow: 0 0 0 0px rgba(0, 255, 136, 0.7); }
            100% { box-shadow: 0 0 0 10px rgba(0, 255, 136, 0); }
        }

        .signal-card {
            background: rgba(10, 10, 10, 0.8);
            border: 1px solid #333;
            margin-bottom: 20px;
            position: relative;
            padding: 15px;
            overflow: hidden;
            cursor: pointer;
        }

        .signal-card::after {
            content: "";
            position: absolute;
            top: 0; left: 0;
            width: 4px; height: 100%;
            background: #00ff88;
        }

        .signal-card.short::after { background: #ff4444; }
        .signal-card.short { border-color: rgba(255, 68, 68, 0.3); }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .symbol { font-family: 'Orbitron', sans-serif; font-size: 18px; color: #fff; }
        .badge {
            font-size: 10px;
            padding: 2px 8px;
            background: #00ff88;
            color: #000;
            font-weight: bold;
        }
        .badge.short { background: #ff4444; }

        .entry-price {
            font-size: 24px;
            text-align: center;
            color: #00ccff;
            margin: 10px 0;
            border: 1px dashed #333;
            padding: 10px;
        }

        .target-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 15px;
        }

        .target-box {
            font-size: 10px;
            text-align: center;
            border: 1px solid #222;
            padding: 5px;
            transition: 0.5s;
        }

        /* --- STYLES FOR HIT TRACKER --- */
        .target-hit {
            border-color: #ffcc00 !important;
            color: #ffcc00 !important;
            background: rgba(255, 204, 0, 0.15);
            box-shadow: inset 0 0 10px #ffcc00;
            font-weight: bold;
        }

        .target-box span { display: block; color: #fff; font-size: 12px; margin-top: 3px; }
        .target-hit span { color: #ffcc00 !important; }

        .sl-box {
            margin-top: 15px;
            padding: 8px;
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid #441111;
            color: #ff4444;
            text-align: center;
            font-size: 12px;
        }

        .prob-bar-container { margin-top: 15px; }
        .prob-text { font-size: 9px; color: #555; display: flex; justify-content: space-between; }
        .prob-bg { width: 100%; height: 3px; background: #111; margin-top: 5px; }
        .prob-fill { height: 100%; background: #00ff88; box-shadow: 0 0 5px #00ff88; }

        .no-signal {
            text-align: center;
            margin-top: 100px;
            color: #333;
            font-size: 14px;
        }

        /* --- STYLES FOR MODAL & ALERTS --- */
        #alert-init-btn { width: 100%; padding: 12px; background: #00ff88; color: #00; border: none; font-family: 'Orbitron'; font-weight: bold; cursor: pointer; margin-bottom: 20px; box-shadow: 0 0 15px #00ff88; }
        
        #modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.98); z-index: 10000; overflow-y: auto; }
        .modal-body { padding: 20px; max-width: 500px; margin: auto; }
        .close-modal { color: #ff4444; text-align: right; margin-bottom: 15px; cursor: pointer; font-size: 14px; font-family: 'Orbitron'; }
        #chart-div { width: 100%; height: 320px; border: 1px solid #333; margin-bottom: 20px; }
        .reason-title { color: #00ff88; font-size: 14px; margin-bottom: 10px; border-bottom: 1px solid #222; padding-bottom: 5px; font-family: 'Orbitron'; }
        .reason-content { color: #ccc; font-size: 13px; line-height: 1.6; }
    </style>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
</head>
<body>
    <div class="app-container">
        <button id="alert-init-btn" onclick="initSystem()">[ INITIALIZE NEURAL INTERFACE ]</button>

        <div class="app-header">
            <h1>NEXUS QUANTUM</h1>
            <div class="status-bar">
                <span><div class="pulse"></div> LIVE_CORE</span>
                <span>ISO_LEVERAGE: 20X</span>
                <span>v5.0.2</span>
            </div>
        </div>

        {% if signals %}
            {% for s in signals %}
            <div class="signal-card {{ 'short' if s.signal == 'SHORT' else '' }}" 
                 onclick="openModal('{{ s.symbol }}', '{{ s.reason }}')">
                <div class="card-header">
                    <div class="symbol">#{{ s.symbol }}</div>
                    <div class="badge {{ 'short' if s.signal == 'SHORT' else '' }}">{{ s.signal }} VECTOR</div>
                </div>
                <div class="entry-price">{{ s.entry }}</div>
                <div class="target-grid">
                    <div class="target-box {{ 'target-hit' if s.tp1_n else '' }}">TARGET 1<span>{{ s.tp1 }}</span></div>
                    <div class="target-box {{ 'target-hit' if s.tp2_n else '' }}">TARGET 2<span>{{ s.tp2 }}</span></div>
                    <div class="target-box {{ 'target-hit' if s.tp3_n else '' }}">TARGET 3<span>{{ s.tp3 }}</span></div>
                </div>
                <div class="sl-box">STOP LOSS: {{ s.sl }}</div>
                <div class="prob-bar-container">
                    <div class="prob-text">
                        <span>NEURAL_CONFIDENCE</span>
                        <span>{{ s.probability }}%</span>
                    </div>
                    <div class="prob-bg"><div class="prob-fill" style="width: {{ s.probability }}%"></div></div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="no-signal">
                [ SEARCHING FOR DEEP LIQUIDITY ]<br>
                <span style="font-size: 10px; color: #111;">SCANNING_ALL_PAIRS_BINANCE_FUTURES</span>
            </div>
        {% endif %}
    </div>

    <div id="modal">
        <div class="modal-body">
            <div class="close-modal" onclick="closeModal()">[ CLOSE_TERMINAL X ]</div>
            <div id="chart-div"></div>
            <div class="reason-title">💡 NEURAL REASONING REPORT:</div>
            <div id="reason-content" class="reason-content"></div>
        </div>
    </div>

    <!-- DUAL AUDIO ALERTS -->
    <audio id="newSigBeep" src="https://assets.mixkit.co/active_storage/sfx/2568/2568-preview.mp3"></audio>
    <audio id="hitChime" src="https://assets.mixkit.co/active_storage/sfx/1435/1435-preview.mp3"></audio>

    <script>
        // Data monitoring untuk perbandingan JS
        const currentData = [
            {% for s in signals %}
            { symbol: "{{ s.symbol }}", tp1: {{ 'true' if s.tp1_n else 'false' }}, tp2: {{ 'true' if s.tp2_n else 'false' }} },
            {% endfor %}
        ];

        function initSystem() {
            Notification.requestPermission();
            // Unlock audio on mobile devices
            document.getElementById('newSigBeep').play().then(() => document.getElementById('newSigBeep').pause());
            document.getElementById('hitChime').play().then(() => document.getElementById('hitChime').pause());
            document.getElementById('alert-init-btn').style.display = 'none';
        }

        function checkPerformance() {
            let lastCache = JSON.parse(localStorage.getItem('nexus_brain') || "[]");
            let playHit = false;
            let playNew = false;

            currentData.forEach(curr => {
                let old = lastCache.find(o => o.symbol === curr.symbol);
                if (!old) {
                    playNew = true; // Koin baru muncul di daftar
                } else {
                    if (curr.tp1 && !old.tp1) playHit = true; // Status TP1 berubah jadi HIT
                    if (curr.tp2 && !old.tp2) playHit = true; // Status TP2 berubah jadi HIT
                }
            });

            if (playHit) {
                document.getElementById('hitChime').play();
            } else if (playNew && lastCache.length > 0) {
                document.getElementById('newSigBeep').play();
                if (Notification.permission === "granted") {
                    new Notification("NEXUS QUANTUM", { body: "New Institutional Signal Identified!" });
                }
            }
            localStorage.setItem('nexus_brain', JSON.stringify(currentData));
        }

        function openModal(symbol, reason) {
            document.getElementById('modal').style.display = 'block';
            document.getElementById('reason-content').innerText = reason;
            new TradingView.widget({
                "width": "100%", "height": 320, "symbol": "BINANCE:" + symbol,
                "interval": "60", "timezone": "Etc/UTC", "theme": "dark", "style": "1",
                "locale": "en", "enable_publishing": false, "hide_top_toolbar": true,
                "container_id": "chart-div"
            });
        }

        function closeModal() {
            document.getElementById('modal').style.display = 'none';
            document.getElementById('chart-div').innerHTML = "";
        }

        checkPerformance();
        
        setInterval(() => {
            if (document.getElementById('modal').style.display !== 'block') {
                location.reload();
            }
        }, 25000);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE, signals=ACTIVE_SIGNALS)

# --- SCANNER TRADINGVIEW ---
def get_tradingview_data(symbol):
    try:
        url = "https://scanner.tradingview.com/crypto/scan"
        payload = {
            "symbols": {
                "tickers": [f"BINANCE:{symbol}"],
                "query": {"types": []}
            },
            "columns": [
                "close","RSI","ADX",
                "EMA50","EMA200",
                "Stoch.K","Stoch.D",
                "AO","Mom","ROC"
            ]
        }
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if not data.get("data"):
            return None
        d = data["data"][0]["d"]
        return {
            "price": d[0],
            "rsi": d[1],
            "adx": d[2],
            "ema50": d[3],
            "ema200": d[4],
            "stoch_k": d[5],
            "stoch_d": d[6],
            "ao": d[7],
            "mom": d[8],
            "roc": d[9]
        }
    except:
        return None

# --- FUNGSI PROTEKSI ---
def is_authorized(uid):
    if not WHITELIST_IDS: return True
    return uid in WHITELIST_IDS

def denied_access(message):
    msg = (
        f"╔══════════════════════╗\n"
        f"    **SYSTEM ACCESS DENIED**\n"
        f"╚══════════════════════╝\n\n"
        f"🔴 **CRITICAL:** ID `{message.from_user.id}` is unregistered.\n"
        f"⚠️ This terminal is encrypted for VIP members only."
    )
    bot.reply_to(message, msg, parse_mode="Markdown")

def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        if entry == 0: return 0
        diff = (target - entry) if str(side).upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

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

def get_multi_tf_technical(symbol):
    try:
        tv_data = get_tradingview_data(symbol)
        if not tv_data:
            return "SKIP"
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

def get_ai_analysis(coin_data):
    if not client_groq: return None
    
    symbol = coin_data.get('symbol')
    price = float(coin_data.get('lastPrice') or coin_data.get('price', 0))

    tv_data = get_tradingview_data(symbol)
    if not tv_data:
        return "SKIP"

    tf_data = get_multi_tf_technical(symbol)
    if tf_data == "INSUFFICIENT" or tf_data is None:
        return "SKIP"

    learning_log = ""
    if TRADE_HISTORY:
        recent = TRADE_HISTORY[-50:]
        learning_log = "\n[PAST PERFORMANCE CONTEXT]:\n" + "\n".join([f"- {r['symbol']}: {r['status']} ({r['roi']:+.1f}%)" for r in recent])
        wins = [t for t in TRADE_HISTORY if t['roi'] > 0]
        win_rate = (len(wins) / len(TRADE_HISTORY)) * 100 if TRADE_HISTORY else 0
        bias = "BULLISH" if win_rate > 55 else "DEFENSIVE"
    else:
        win_rate = 0
        bias = "NEUTRAL"

    prompt = f"""
    Role: Lead Quantitative Researcher at Hedge Fund.
    System Status: Analyze {symbol} at {format_price(price)}.
    Matrix: 4H Trend {tf_data['trend_4h']}, 1H Price Action.
    {learning_log}

    [QUANT LEARNING METRICS]
    - Win Rate: {win_rate:.1f}% | Bias: {bias}

    Task: Berikan Sniper Signal berbasis Machine Learning SMC & Quantitative Model.
    Logic Protocols:
    1. Dynamic Confidence: Hitung skor probabilitas unik (Range 81% - 99%).
    2. Architecture: AMD Logic. Cari area Discount.
    3. Exit Strategy: Fibonacci 1.618.
    4. NO Scientific Notation.
    
[REAL-TIME TECHNICAL DATA - TRADINGVIEW]
- RSI: {tv_data['rsi']}
- ADX: {tv_data['adx']}
- EMA50: {tv_data['ema50']}
- EMA200: {tv_data['ema200']}
- Stochastic: K={tv_data['stoch_k']} D={tv_data['stoch_d']}
- Momentum: {tv_data['mom']}
- ROC: {tv_data['roc']}

    Output JSON ONLY:
    {{
        "symbol": "{symbol}", "signal": "LONG/SHORT/WAIT", "entry": {price},
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "probability": 0,
        "reason": "Expert SMC terminology."
    }}
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=25
        )
        return json.loads(completion.choices[0].message.content)
    except:
        return None

def send_signal_ui(sig_data, target_chat):
    if not sig_data or sig_data == "SKIP": return
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal', 'WAIT')).upper()
    entry, tp1, tp2, tp3, sl = sig_data.get('entry', 0), sig_data.get('tp1', 0), sig_data.get('tp2', 0), sig_data.get('tp3', 0), sig_data.get('sl', 0)
    if not symbol or side not in ['LONG', 'SHORT'] or entry == 0: return

    roi1, roi2, roi3 = calculate_roi(entry, tp1, side), calculate_roi(entry, tp2, side), calculate_roi(entry, tp3, side)
    side_label = "▲ BULLISH VECTOR" if side == "LONG" else "▼ BEARISH VECTOR"

    try:
        prob = int(float(sig_data.get('probability', 85)))
    except:
        prob = 85

    meter_fill = int(prob // 10)
    meter = "⬥" * meter_fill + "⬦" * (10 - meter_fill)
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

    msg = (
        f"╔══════════════════════╗\n"
        f"  **NEXUS QUANTUM TERMINAL**\n"
        f"╚══════════════════════╝\n\n"
        f"⬥ **IDENTIFIER:** `#{symbol}`\n"
        f"⬥ **EXECUTION:** `{side_label}`\n"
        f"⬥ **ALGORITHM:** `Neural-SMC v4.0 | AI-Quant Engine`\n"
        f"⬥ **STRENGTH:** `[{meter}] {prob}%` \n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"┌─── **ENTRY CORRIDOR** ───┐\n"
        f"   ` {format_price(entry)} `\n"
        f"└──────────────────────┘\n\n"
        f"⬥ **QUANTITATIVE TARGETS**\n"
        f"  ├─ **T1:** `{format_price(tp1)}` (`{roi1:+.1f}%`)\n"
        f"  ├─ **T2:** `{format_price(tp2)}` (`{roi2:+.1f}%`)\n"
        f"  └─ **T3:** `{format_price(tp3)}` (`{roi3:+.1f}%`)\n\n"
        f"⬥ **RISK MITIGATION (SL)**\n"
        f"  └─ `{format_price(sl)}` (Isolated 20x)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 **NEURAL REASONING:**\n"
        f"_{sig_data.get('reason', 'No data from model')}_\n\n"
        f"🔗 [ACCESS REAL-TIME DATA HUB]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**SMC GLOBAL • INSTITUTIONAL GRADE**"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)
    if not any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS):
        ACTIVE_SIGNALS.append(sig_data)

# --- MONITOR SIGNALS ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, TRADE_HISTORY, COOLDOWN_COINS
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol, entry, side = sig['symbol'], float(sig['entry']), sig['signal'].upper()
                tp1, tp2, tp3, sl = float(sig['tp1']), float(sig['tp2']), float(sig['tp3']), float(sig['sl'])
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr, roi = float(res['price']), calculate_roi(entry, float(res['price']), side)

                is_finished, status = False, ""
                if (side == "LONG" and curr <= sl) or (side == "SHORT" and curr >= sl):
                    status, is_finished = "🛑 SL HIT", True
                elif (side == "LONG" and curr >= tp3) or (side == "SHORT" and curr <= tp3):
                    status, is_finished = "🎯 TP3 HIT", True
                elif (side == "LONG" and curr >= tp2) or (side == "SHORT" and curr <= tp2):
                    if not sig.get('tp2_n'):
                        bot.send_message(CHAT_ID, f"✅ **T2 CORRIDOR BREACHED**\nAsset: #{symbol}\nROI: {roi:+.1f}%"); sig['tp2_n'] = True
                elif (side == "LONG" and curr >= tp1) or (side == "SHORT" and curr <= tp1):
                    if not sig.get('tp1_n'):
                        bot.send_message(CHAT_ID, f"✅ **T1 CORRIDOR BREACHED**\nAsset: #{symbol}\nROI: {roi:+.1f}%"); sig['tp1_n'] = True

                if is_finished:
                    bot.send_message(CHAT_ID, f"{status}\n#{symbol}\nROI: {roi:+.1f}%\nExit: {format_price(curr)}")
                    TRADE_HISTORY.append({"symbol": symbol, "roi": roi, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()})
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=4)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60)
        except:
            time.sleep(60)

# --- DAILY REPORT ---
def daily_report_scheduler():
    global TRADE_HISTORY
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute == 0:
            yesterday = now - timedelta(days=1)
            trades = [t for t in TRADE_HISTORY if datetime.fromisoformat(t['timestamp']) > yesterday]
            if trades:
                total_roi = sum([t['roi'] for t in trades])
                wr = (len([t for t in trades if t['roi'] > 0]) / len(trades)) * 100
                bot.send_message(CHAT_ID, f"📊 **NEXUS DAILY QUANT REPORT**\n━━━━━━━━━━━━━━\n✅ Vectors: {len(trades)}\n🏆 Accuracy: {wr:.1f}%\n💰 Total ROI: {total_roi:+.2f}%")
            time.sleep(70)
        time.sleep(30)

# --- RUN SCANNER ---
def run_scanner():
    global COOLDOWN_COINS
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    targets = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:4] + sorted(valid, key=lambda x: float(x['priceChangePercent']))[:4] + sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:2]
    for t in {v['symbol']: v for v in targets}.values():
        if any(s.get('symbol') == t['symbol'] for s in ACTIVE_SIGNALS) or t['symbol'] in COOLDOWN_COINS: continue
        sig = get_ai_analysis(t)
        if sig and sig != "SKIP":
            send_signal_ui(sig, CHAT_ID)
            time.sleep(15)

# --- TELEGRAM HANDLERS ---
@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.lower().startswith('cek'))
def manual_check(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    try:
        parts = message.text.split()
        if len(parts) < 2: return
        coin = "".join(re.findall(r'[A-Z0-9]', parts[1].upper()))
        symbol = f"{coin}USDT"
        sent_msg = bot.send_message(message.chat.id, f"🔍 `QUANTUM_SCANNING:` **{symbol}**...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        if res:
            sig = get_ai_analysis(res)
            bot.delete_message(message.chat.id, sent_msg.message_id)
            if sig == "SKIP" or not sig:
                bot.send_message(message.chat.id, f"⚠️ `INSUFFICIENT_DATA:` {symbol}")
            elif sig:
                send_signal_ui(sig, message.chat.id)
        else:
            bot.send_message(message.chat.id, f"❌ `IDENTIFIER_NOT_FOUND:` {symbol}")
    except:
        pass

@bot.message_handler(commands=['start'])
def start_cmd(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🛰️ INITIATE SCAN"), KeyboardButton("🖥️ CORE STATUS"))
    bot.send_message(message.chat.id, "⚡ **NEXUS QUANTUM CORE ONLINE**", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛰️ INITIATE SCAN")
def manual_scan(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    bot.reply_to(message, "🔄 `INITIATING_ASYNC_SCANNER...`")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "🖥️ CORE STATUS")
def status_btn(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    bot.send_message(message.chat.id, f"🟢 **SYSTEM DIAGNOSTICS: OPTIMAL**\n🎯 Signals Monitored: {len(ACTIVE_SIGNALS)}")

if __name__ == "__main__":
    # JALANKAN WEB SERVER UNTUK APLIKASI
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False), daemon=True).start()
    
    # JALANKAN PROSES BACKROUND
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=daily_report_scheduler, daemon=True).start()

    def scheduler():
        while True:
            run_scanner()
            time.sleep(3600)

    threading.Thread(target=scheduler, daemon=True).start()
    bot.infinity_polling(skip_pending=True)