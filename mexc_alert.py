import time
import requests
import pandas as pd
import pandas_ta as ta

# --- ข้อมูล Telegram ---
TELEGRAM_TOKEN = "8389657782:AAGYbKxFBC-GD1_BMMCOvS5GQ2bg8pnRSg4"
CHAT_ID = "วาง_เลข_ID_ตรงนี้"  # เปลี่ยนตรงนี้เป็นเลข Id ที่ได้จาก @userinfobot

SYMBOL = "ETH_USDT"  # เปลี่ยนคู่เหรียญที่ต้องการเฝ้าได้ เช่น "ONE_USDT"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Send Error:", e)

def fetch_mexc_kline(symbol):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min15"
        res = requests.get(url, timeout=5).json()
        if res.get("success") and "data" in res:
            df = pd.DataFrame({
                "close": res["data"]["close"],
                "high": res["data"]["high"],
                "low": res["data"]["low"]
            })
            return df
    except Exception as e:
        print("Fetch Error:", e)
    return None

def analyze_and_notify():
    df = fetch_mexc_kline(SYMBOL)
    if df is None or len(df) < 30:
        return

    # คำนวณ Indicator
    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACDh'] = macd['MACDh_12_26_9']

    price = df['close'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    macdh = df['MACDh'].iloc[-1]
    prev_macdh = df['MACDh'].iloc[-2]

    signal = None
    if rsi < 30 or (macdh > prev_macdh and macdh < 0):
        signal = "🟢 <b>BUY / LONG Signal</b>"
    elif rsi > 70 or (macdh < prev_macdh and macdh > 0):
        signal = "🔴 <b>SELL / SHORT Signal</b>"

    if signal:
        msg = f"""🚨 <b>MEXC Alert ({SYMBOL})</b> 🚨
ราคาปัจจุบัน: <b>${price:,.4f}</b>
• RSI (14): {rsi:.2f}
• MACD Hist: {macdh:.6f}
---------------------------------
สัญญาณ: {signal}"""
        send_telegram(msg)

print("เริ่มการทำงานของระบบเฝ้ากระดาน MEXC...")
send_telegram(f"🚀 ระบบ AI เฝ้ากระดาน MEXC ({SYMBOL}) เริ่มทำงานแล้วค่ะ")

while True:
    analyze_and_notify()
    time.sleep(60)