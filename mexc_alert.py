import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from flask import Flask

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

SYMBOLS = ["ETH_USDT", "DOGE_USDT", "XRP_USDT", "TRUMP_USDT", "ONE_USDT"]

bot_started = False
lock = threading.Lock()

def normalize_symbol(symbol):
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        s = s[:-4] + "_USDT" if s.endswith("USDT") else s + "_USDT"
    return s

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram API Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
    """ดึงข้อมูลกราฟ (Hour4 = ระยะสั้น, Week1 = ระยะยาว)"""
    try:
        clean_symbol = normalize_symbol(symbol)
        url = f"https://contract.mexc.com/api/v1/contract/kline/{clean_symbol}?interval={interval}"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            data = res["data"]
            if "close" in data and len(data["close"]) > 0:
                df = pd.DataFrame({
                    "close": [float(x) for x in data["close"]],
                    "high": [float(x) for x in data["high"]],
                    "low": [float(x) for x in data["low"]]
                })
                return df
    except Exception as e:
        print(f"[MEXC API Error - {symbol}]: {e}", file=sys.stderr, flush=True)
    return None

def generate_analysis_text(symbol, interval):
    df = fetch_mexc_kline(symbol, interval)
    if df is None or len(df) < 30:
        return None

    # คำนวณ Indicator 7 ตัว
    df['RSI'] = ta.rsi(df['close'], length=14)
    
    stoch = ta.stoch(df['high'], df['low'], df['close'])
    stoch_col = [c for c in stoch.columns if 'STOCHk' in c]
    df['STOCH'] = stoch[stoch_col[0]] if stoch_col else 50.0
    
    bb = ta.bbands(df['close'], length=20)
    bb_col = [c for c in bb.columns if 'BBM' in c]
    df['BB_MID'] = bb[bb_col[0]] if bb_col else df['close']
    
    psar = ta.psar(df['high'], df['low'], df['close'])
    psar_l_col = [c for c in psar.columns if 'PSARl' in c]
    psar_s_col = [c for c in psar.columns if 'PSARs' in c]
    df['PSAR_L'] = psar[psar_l_col[0]] if psar_l_col else np.nan
    df['PSAR_S'] = psar[psar_s_col[0]] if psar_s_col else np.nan
    
    df['EMA'] = ta.ema(df['close'], length=20)
    df['CCI'] = ta.cci(df['high'], df['low'], df['close'], length=20)
    
    macd = ta.macd(df['close'])
    macd_h_col = [c for c in macd.columns if 'MACDh' in c]
    df['MACD_H'] = macd[macd_h_col[0]] if macd_h_col else 0.0

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    # คำนวณแนวรับ-แนวต้านจาก Pivot Point ของแท่งเทียนก่อนหน้า
    pivot = (prev['high'] + prev['low'] + prev['close']) / 3
    s1 = (2 * pivot) - prev['high']
    r1 = (2 * pivot) - prev['low']
    
    price = curr['close']
    
    # ดึงค่า Indicator ล่าสุด พร้อมป้องกันค่าว่าง (NaN)
    rsi = curr['RSI'] if pd.notna(curr['RSI']) else 50.0
    stoch_val = curr['STOCH'] if pd.notna(curr['STOCH']) else 50.0
    bb_val = curr['BB_MID'] if pd.notna(curr['BB_MID']) else price
    sar_l = curr['PSAR_L']
    sar_s = curr['PSAR_S']
    ema = curr['EMA'] if pd.notna(curr['EMA']) else price
    cci = curr['CCI'] if pd.notna(curr['CCI']) else 0.0
    macd_val = curr['MACD_H'] if pd.notna(curr['MACD_H']) else 0.0

    up_count = 0
    down_count = 0

    def get_dir(is_up):
        nonlocal up_count, down_count
        if is_up:
            up_count += 1
            return "🟢"
        else:
            down_count += 1
            return "🔴"

    rsi_dir = get_dir(rsi > 50)
    stoch_dir = get_dir(stoch_val > 50)
    bb_dir = get_dir(price > bb_val)
    
    if pd.notna(sar_l):
        sar_val = sar_l
        sar_dir = get_dir(True)
    else:
        sar_val = sar_s if pd.notna(sar_s) else price
        sar_dir = get_dir(False)
        
    ema_dir = get_dir(price > ema)
    cci_dir = get_dir(cci > 0)
    macd_dir = get_dir(macd_val > 0)

    # กฎการวิเคราะห์ตามที่พี่โด่งกำหนด
    if up_count > down_count:
        signal = "🟢 BUY / LONG Signal (สมหวัง)"
    elif down_count > up_count:
        signal = "🔴 SELL / SHORT Signal (ยุ่งเหยิง)"
    else:
        signal = "⚪ NEUTRAL Signal (ไม่แน่นอน)"

    return f"""ราคาปัจจุบัน: <b>${price:,.4f}</b>
แนวรับ : ${s1:,.4f}
แนวต้าน : ${r1:,.4f}
• RSI : {rsi:.2f} {rsi_dir}
• Stochastic : {stoch_val:.4f} {stoch_dir}
• Bollinger : {bb_val:.4f} {bb_dir}
• SAR : {sar_val:.4f} {sar_dir}
• EMA 20 : {ema:.4f} {ema_dir}
• CCI 20 : {cci:.4f} {cci_dir}
• MACD : {macd_val:.6f} {macd_dir}
---------------------------------
สัญญาณ: {signal}"""

def analyze_and_notify(symbol):
    clean_symbol = normalize_symbol(symbol)
    
    short_term = generate_analysis_text(clean_symbol, "Hour4")
    long_term = generate_analysis_text(clean_symbol, "Week1")
    
    if not short_term or not long_term:
        return

    msg = f"""🚨 <b>MEXC Alert ({clean_symbol})</b>

<b>วิเคราะห์ระยะสั้น 1-4 ชั่วโมง</b>
{short_term}

<b>วิเคราะห์ระยะยาว 1w-1m</b>
{long_term}"""
    
    send_telegram(msg)

def bot_loop():
    send_telegram(f"🚀 <b>ผู้ช่วยเทรด MEXC</b> เฝ้ากราฟแบบ 7 Indicators (4H & 1W) เริ่มต้นทำงานแล้วค่ะ!")
    
    while True:
        for s in SYMBOLS:
            analyze_and_notify(s)
            time.sleep(5)
        
        # หน่วงเวลา 1 ชั่วโมงเพื่อเช็กกราฟรอบใหม่ (ป้องกันแจ้งเตือนรัวเกินไปสำหรับกราฟ 4H/1W)
        time.sleep(3600) 

def start_bot_thread():
    global bot_started
    with lock:
        if not bot_started:
            bot_started = True
            threading.Thread(target=bot_loop, daemon=True).start()
            print("[System] 7-Indicators Bot Loop started!", file=sys.stdout, flush=True)

@app.route('/')
def home():
    start_bot_thread()
    return "MEXC 7-Indicators Bot is running 24/7!"

start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
