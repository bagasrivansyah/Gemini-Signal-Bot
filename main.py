import os
import requests
import telebot
import json
import time
import threading
from flask import Flask, render_template_string

TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM", "")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT = int(os.getenv("PORT", 8080))

ACTIVE_SIGNALS = []

app = Flask(__name__)

# Check if token exists before creating bot
if TOKEN_TELEGRAM:
    bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=15)
else:
    bot = None
    print("[WARNING] TOKEN_TELEGRAM not set - Bot will not function")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>NEXUS QUANTUM</title>
    <style>
        body { background: #000; color: #00ff88; font-family: monospace; padding: 20px; }
        .header { text-align: center; border-bottom: 1px solid #00ff88; padding: 20px 0; margin-bottom: 20px; }
        .no-signal { text-align: center; margin-top: 50px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>NEXUS QUANTUM</h1>
        <p>Status: Online</p>
    </div>
    <div class="no-signal">Bot is running...</div>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health():
    return {'status': 'ok'}, 200

if bot:
    @bot.message_handler(commands=['start'])
    def start_cmd(message):
        bot.send_message(message.chat.id, "NEXUS QUANTUM ONLINE")

    @bot.message_handler(func=lambda m: m.text == "Scan")
    def scan_cmd(message):
        bot.send_message(message.chat.id, "Scanning...")

def run_bot():
    if bot:
        try:
            print("[BOT] Starting bot polling...")
            bot.infinity_polling(skip_pending=True)
        except Exception as e:
            print(f"[BOT] Error: {e}")
    else:
        print("[BOT] Bot not initialized (TOKEN_TELEGRAM missing)")
        while True:
            time.sleep(60)

if __name__ == "__main__":
    print(f"[NEXUS] Starting application on port {PORT}...")
    
    # Start web server
    print("[NEXUS] Starting web server...")
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False, debug=False), daemon=True).start()
    
    # Start bot
    print("[NEXUS] Starting bot...")
    threading.Thread(target=run_bot, daemon=False).start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[NEXUS] Shutting down...")
