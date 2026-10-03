import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
from flask import Flask

# บังคับให้ Python พิมพ์ Log ออกทันที ไม่ต้องรอ Buffer บน Render
sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

# รายชื่อคู่เหรียญที่ต้องการเฝ้าระวัง
SYMBOLS = ["ETH_USDT", "DOGE_USDT", "XRP_USDT", "TRUMP_USDT", "ONE_USDT"]

def normalize_symbol(symbol):
    """แปลงชื่อเหรียญให้อยู่ในรูปแบบ XXX_USDT สำหรับ MEXC Futures อัตโนมัติ"""
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        if s.endswith("USDT"):
            s = s[:-4] + "_USDT"
        else:
            s = s + "_USDT"
    return s

def send_telegram(message):
    """ส่งข้อความเข้า Telegram พร้อมคืนค่าผลลัพธ์เพื่อตรวจสอบ"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"[Telegram API] Status: {res.status_code}, Response: {res.text}", flush=True)
        return res.json()
    except Exception as e:
        print(f"[Telegram API Error]: {e}", flush=True)
        return {"ok": False, "error": str(e)}

def fetch_mexc_kline(symbol):
    """ดึงข้อมูลกราฟ K-line จาก MEXC Contract API"""
    try:
        clean_symbol = normalize_symbol(symbol)
        url = f"https://contract.mexc.com/api/v1/contract/kline/{clean_symbol}?interval=Min15"
        res = requests.get(url, timeout=5).json()
        if res.get("success") and "data" in res and isinstance(res["data"], dict):
            data = res["data"]
            if "close" in data and len(data["close"]) > 0:
                df = pd.DataFrame({
                    "close": [float(x) for x in data["close"]],
                    "high": [float(x) for x in data["high"]],
                    "low": [float(x) for x in data["low"]]
                })
                return df
    except Exception as e:
        print(f"[MEXC API Error - {symbol}]: {e}", flush=True)
    return None

def analyze_and_notify(symbol):
    clean_symbol = normalize_symbol(symbol)
    df = fetch_mexc_kline(clean_symbol)
    if df is None or len(df) < 30:
        return

    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACDh'] = macd['MACDh_12_26_9']

    price = float(df['close'].iloc[-1])
    rsi = float(df['RSI'].iloc[-1])
    macdh = float(df['MACDh'].iloc[-1])
    prev_macdh = float(df['MACDh'].iloc[-2])

    signal = None
    if rsi < 30 or (macdh > prev_macdh and macdh < 0):
        signal = "🟢 <b>BUY / LONG Signal</b>"
    elif rsi > 70 or (macdh < prev_macdh and macdh > 0):
        signal = "🔴 <b>SELL / SHORT Signal</b>"

    if signal:
        msg = f"""🚨 <b>MEXC Alert ({clean_symbol})</b> 🚨
ราคาปัจจุบัน: <b>${price:,.4f}</b>
• RSI (14): {rsi:.2f}
• MACD Hist: {macdh:.6f}
---------------------------------
สัญญาณ: {signal}"""
        send_telegram(msg)

def bot_loop():
    formatted_symbols = [normalize_symbol(s) for s in SYMBOLS]
    symbols_text = ", ".join(formatted_symbols)
    send_telegram(f"🚀 <b>ผู้ช่วยเทรด MEXC</b> เริ่มทำงานเฝ้ากราฟ ({symbols_text}) เรียบร้อยแล้วค่ะ")
    
    while True:
        for s in SYMBOLS:
            analyze_and_notify(s)
            time.sleep(2)
        time.sleep(60)

bot_thread = None

def start_bot_thread():
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=bot_loop, daemon=True)
        bot_thread.start()
        print("[System] Background Bot Loop started!", flush=True)

@app.route('/')
def home():
    start_bot_thread()
    return "MEXC Multi-Symbol Bot is running 24/7!"

@app.route('/test')
def test_send():
    """เปิดหน้านี้เพื่อบังคับยิงข้อความทดสอบเข้า Telegram ทันที"""
    start_bot_thread()
    res = send_telegram("🔔 <b>ทดสอบการเชื่อมต่อ</b>: ระบบส่งข้อความหาพี่โด่งสำเร็จแล้วค่ะ!")
    return f"Telegram Response: {res}"

start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
