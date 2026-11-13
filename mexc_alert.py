import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, date
from flask import Flask

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

MEME_KEYWORDS = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "TRUMP", "BOME", "NEIRO", "WIF", "PNUT", "GOAT", "MOODENG", "MEME", "CHILLGUY", "BTT", "BABYDOGE", "PORK", "SUNDOG"]

TOP10_SYMBOLS = []
MEME_SYMBOLS = []
SYMBOLS = []

show_tech_details = False

bot_started = False
lock = threading.Lock()

last_alert_sent = {}
last_update_id = 0

top10_daily_state = {}
symbol_last_alert_time = {}

def normalize_symbol(symbol):
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        s = s[:-4] + "_USDT" if s.endswith("USDT") else s + "_USDT"
    return s

def fetch_top_symbols_from_mexc():
    global TOP10_SYMBOLS, MEME_SYMBOLS, SYMBOLS
    try:
        url = "https://contract.mexc.com/api/v1/contract/ticker"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            tickers = res["data"]
            usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("_USDT")]
            usdt_tickers.sort(key=lambda x: float(x.get("amount24", 0) or 0), reverse=True)
            
            top_10 = []
            meme_candidates = []
            
            for t in usdt_tickers:
                sym = t.get("symbol")
                if not sym:
                    continue
                
                norm_sym = normalize_symbol(sym)
                is_meme = any(kw in sym for kw in MEME_KEYWORDS)
                
                if not is_meme:
                    if len(top_10) < 10:
                        top_10.append(norm_sym)
                else:
                    meme_candidates.append(norm_sym)
                        
                if len(top_10) >= 10 and len(meme_candidates) >= 30:
                    break
            
            filtered_memes = []
            for m in meme_candidates:
                if m not in top_10:
                    if m not in filtered_memes:
                        filtered_memes.append(m)
                if len(filtered_memes) >= 10:
                    break
            
            if top_10:
                TOP10_SYMBOLS = top_10
            if filtered_memes:
                MEME_SYMBOLS = filtered_memes
            
            SYMBOLS = list(set(TOP10_SYMBOLS + MEME_SYMBOLS))
            print(f"[System] Auto-fetched Top 10 Volume & Non-overlapping Meme Coins successfully!", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"[API Error fetching top symbols]: {e}", file=sys.stderr, flush=True)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram API Error]: {e}", file=sys.stderr, flush=True)

def handle_telegram_commands():
    global SYMBOLS, TOP10_SYMBOLS, MEME_SYMBOLS, show_tech_details, last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=2"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("ok"):
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id"))
                
                if chat_id == CHAT_ID:
                    text = message.get("text", "").strip().lower()
                    
                    if text == "/list":
                        if not TOP10_SYMBOLS and not MEME_SYMBOLS:
                            list_msg = (
                                "⏳ <b>รอประมวลผล...</b>\n"
                                "<i>(ระบบกำลังดึงข้อมูล Top Volume และ Meme Coins จาก MEXC API)</i>\n\n"
                                "<b>📚 คู่มือการใช้งานเบื้องต้น:</b>\n"
                                "• <b>/list</b> ดูรายชื่อคู่เหรียญเฝ้าระวัง\n"
                                "• <b>/indicators</b> ดูรายชื่ออินดิเคเตอร์\n"
                                "• <b>/tech</b> เปิด/ปิด การแสดงผลรายละเอียดอินดิเคเตอร์\n"
                                "• <b>/help</b> ดูคู่มือทั้งหมด"
                            )
                        else:
                            top_str = ", ".join([s.replace('_', '/') for s in TOP10_SYMBOLS]) if TOP10_SYMBOLS else "รอประมวลผล..."
                            meme_str = ", ".join([s.replace('_', '/') for s in MEME_SYMBOLS]) if MEME_SYMBOLS else "รอประมวลผล..."
                            list_msg = (
                                "📋 <b>รายชื่อคู่เหรียญเฝ้าระวังปัจจุบัน (ดึงอัตโนมัติ):</b>\n\n"
                                f"<b>🥇 กลุ่ม 1 (Top 10 Volume - หน่วง 10 นาที / แจ้งเตือนสูงสุด 6 ครั้ง / หยุดถ้าไม่มี Short สวน):</b>\n• {top_str}\n\n"
                                f"<b>🥈 กลุ่ม 2 (Top 10 Meme Coins - หน่วง 1 ชั่วโมง):</b>\n• {meme_str}"
                            )
                        send_telegram(list_msg)
                        
                    elif text == "/indicators":
                        ind_msg = (
                            "<b>📊 รายชื่ออินดิเคเตอร์ (10 ตัว)</b>\n"
                            "<i>(กลุ่ม 1 ต้องสอดคล้อง 100% + ผ่าน 7/10 ขึ้นไป)</i>\n\n"
                            "<b>🥇 กลุ่ม 1: เทรนด์ & โมเมนตัม</b>\n"
                            "• EMA 20\n"
                            "• MACD\n"
                            "• RSI\n\n"
                            "<b>🥈 กลุ่ม 2: กรอบราคา & ความผันผวน</b>\n"
                            "• Bollinger Bands\n"
                            "• Parabolic SAR\n"
                            "• Stochastic Oscillator\n\n"
                            "<b>🥉 กลุ่ม 3: อินดิเคเตอร์เสริม</b>\n"
                            "• CCI 20\n"
                            "• Williams %R\n"
                            "• Awesome Oscillator (AO)\n"
                            "• Momentum (MOM)"
                        )
                        send_telegram(ind_msg)
                        
                    elif text == "/tech":
                        show_tech_details = not show_tech_details
                        status_str = "เปิด (ON)" if show_tech_details else "ปิด (OFF)"
                        send_telegram(f"⚙️ สลับสถานะการแสดงผลรายละเอียดอินดิเคเตอร์: <b>{status_str}</b>")
                        
                    elif text == "/help":
                        help_msg = (
                            "<b>📚 คู่มือใช้งานบอทเทรด MEXC</b>\n\n"
                            "• <b>/list</b> ดูรายชื่อคู่เหรียญทั้งหมด\n"
                            "• <b>/indicators</b> ดูรายชื่ออินดิเคเตอร์\n"
                            "• <b>/tech</b> เปิด/ปิด การแสดงผลรายละเอียดอินดิเคเตอร์\n"
                            "• <b>/help</b> ดูคู่มือการใช้งาน"
                        )
                        send_telegram(help_msg)
                        
    except Exception as e:
        print(f"[Command Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
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

def analyze_symbol_data(symbol, interval):
    df = fetch_mexc_kline(symbol, interval)
    if df is None or len(df) < 35:
        return None

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

    willr = ta.willr(df['high'], df['low'], df['close'], length=14)
    df['WILLR'] = willr if isinstance(willr, pd.Series) else -50.0

    ao = ta.ao(df['high'], df['low'])
    df['AO'] = ao if isinstance(ao, pd.Series) else 0.0

    mom = ta.mom(df['close'], length=10)
    df['MOM'] = mom if isinstance(mom, pd.Series) else 0.0

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    pivot = (prev['high'] + prev['low'] + prev['close']) / 3
    s1 = (2 * pivot) - prev['high']
    r1 = (2 * pivot) - prev['low']
    
    price = curr['close']
    rsi = curr['RSI'] if pd.notna(curr['RSI']) else 50.0
    stoch_val = curr['STOCH'] if pd.notna(curr['STOCH']) else 50.0
    bb_val = curr['BB_MID'] if pd.notna(curr['BB_MID']) else price
    sar_l = curr['PSAR_L']
    sar_s = curr['PSAR_S']
    ema = curr['EMA'] if pd.notna(curr['EMA']) else price
    cci = curr['CCI'] if pd.notna(curr['CCI']) else 0.0
    macd_val = curr['MACD_H'] if pd.notna(curr['MACD_H']) else 0.0
    willr_val = curr['WILLR'] if pd.notna(curr['WILLR']) else -50.0
    ao_val = curr['AO'] if pd.notna(curr['AO']) else 0.0
    mom_val = curr['MOM'] if pd.notna
