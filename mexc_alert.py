import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime
from flask import Flask

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

# รายชื่อคีย์เวิร์ดสำหรับคัดแยกเหรียญมีมยอดฮิต
MEME_KEYWORDS = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "TRUMP", "BOME", "NEIRO", "WIF", "PNUT", "GOAT", "MOODENG", "MEME", "CHILLGUY", "BTT", "BABYDOGE", "PORK", "SUNDOG"]

# ตัวแปรเก็บรายชื่อเหรียญแบบไดนามิก
TOP10_SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "BNB_USDT", "ADA_USDT", "AVAX_USDT", "LINK_USDT", "SUI_USDT", "NEAR_USDT"]
MEME_SYMBOLS = ["DOGE_USDT", "SHIB_USDT", "PEPE_USDT", "TRUMP_USDT", "FLOKI_USDT", "BONK_USDT"]
SYMBOLS = TOP10_SYMBOLS + MEME_SYMBOLS

bot_started = False
lock = threading.Lock()

last_alert_sent = {}      # {symbol: {"price": ..., "s1": ..., "r1": ..., "signal": ...}} สำหรับเทียบเงื่อนไขราคา
last_update_id = 0        # สำหรับเช็คข้อความคำสั่งจาก Telegram

def normalize_symbol(symbol):
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        s = s[:-4] + "_USDT" if s.endswith("USDT") else s + "_USDT"
    return s

def fetch_top_symbols_from_mexc():
    """ดึงข้อมูล Top 10 Volume ทั่วไป และ Top 10 Meme Coins จาก MEXC API แบบอัตโนมัติ"""
    global TOP10_SYMBOLS, MEME_SYMBOLS, SYMBOLS
    try:
        url = "https://contract.mexc.com/api/v1/contract/ticker"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            tickers = res["data"]
            usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("_USDT")]
            usdt_tickers.sort(key=lambda x: float(x.get("amount24", 0) or 0), reverse=True)
            
            top_10 = []
            meme_list = []
            
            for t in usdt_tickers:
                sym = t.get("symbol")
                if not sym:
                    continue
                
                is_meme = any(kw in sym for kw in MEME_KEYWORDS)
                
                if is_meme:
                    if len(meme_list) < 10:
                        meme_list.append(sym)
                else:
                    if len(top_10) < 10:
                        top_10.append(sym)
                        
                if len(top_10) >= 10 and len(meme_list) >= 10:
                    break
            
            if top_10:
                TOP10_SYMBOLS = top_10
            if meme_list:
                MEME_SYMBOLS = meme_list
            SYMBOLS = list(set(TOP10_SYMBOLS + MEME_SYMBOLS))
            print(f"[System] Auto-fetched Top 10 Volume & Meme Coins successfully!", file=sys.stdout, flush=True)
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
    """ตรวจสอบและจัดการคำสั่งที่พิมพ์มาจาก Telegram แชทส่วนตัว"""
    global SYMBOLS, TOP10_SYMBOLS, MEME_SYMBOLS, last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("ok"):
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id"))
                
                if chat_id == CHAT_ID:
                    text = message.get("text", "").strip()
                    
                    if text.startswith("/add "):
                        raw_sym = text.replace("/add", "").strip()
                        clean_s = normalize_symbol(raw_sym)
                        if clean_s not in SYMBOLS:
                            SYMBOLS.append(clean_s)
                            send_telegram(f"✅ เพิ่มคู่เหรียญ <b>{clean_s.replace('_', '/')}</b> เข้าสู่ระบบเรียบร้อยค่ะ!")
                        else:
                            send_telegram(f"ℹ️ คู่เหรียญ <b>{clean_s.replace('_', '/')}</b> มีอยู่ในรายการอยู่แล้วค่ะ")
                            
                    elif text.startswith("/remove "):
                        raw_sym = text.replace("/remove", "").strip()
                        clean_s = normalize_symbol(raw_sym)
                        if clean_s in TOP10_SYMBOLS:
                            TOP10_SYMBOLS.remove(clean_s)
                        if clean_s in MEME_SYMBOLS:
                            MEME_SYMBOLS.remove(clean_s)
                        if clean_s in SYMBOLS:
                            SYMBOLS.remove(clean_s)
                            send_telegram(f"🗑️ ลบคู่เหรียญ <b>{clean_s.replace('_', '/')}</b> เรียบร้อยค่ะ!")
                        else:
                            send_telegram(f"❌ ไม่พบเหรียญ <b>{clean_s.replace('_', '/')}</b> ในรายการเฝ้าระวังค่ะ")
                            
                    elif text == "/list":
                        top_str = ", ".join([s.replace('_', '/') for s in TOP10_SYMBOLS])
                        meme_str = ", ".join([s.replace('_', '/') for s in MEME_SYMBOLS])
                        list_msg = (
                            "📋 <b>รายชื่อคู่เหรียญเฝ้าระวังปัจจุบัน (ดึงอัปเดตอัตโนมัติ):</b>\n\n"
                            f"<b>🥇 กลุ่ม 1 (Top 10 Volume - แจ้งเตือนเฉพาะ LONG):</b>\n• {top_str}\n\n"
                            f"<b>🥈 กลุ่ม 2 (Meme Coins Volume สูง - แจ้งเตือน Long/Short):</b>\n• {meme_str}"
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
                        
                    elif text == "/help":
                        help_msg = (
                            "<b>📚 คู่มือใช้งานบอทเทรด MEXC</b>\n\n"
                            "• <b>/add <คู่เหรียญ></b> (เช่น /add BTC_USDT) เพื่อเพิ่มคู่เหรียญ\n"
                            "• <b>/remove <คู่เหรียญ></b> (เช่น /remove DOGE_USDT) เพื่อลบคู่เหรียญ\n"
                            "• <b>/list</b> ดูรายชื่อคู่เหรียญทั้งหมด (แบ่งตามกลุ่ม)\n"
                            "• <b>/indicators</b> ดูรายชื่ออินดิเคเตอร์\n"
                            "• <b>/help</b> ดูคู่มือการใช้งาน"
                        )
                        send_telegram(help_msg)
                        
    except Exception as e:
        print(f"[Command Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
    """ดึงข้อมูลกราฟจาก MEXC API โดยใช้รูปแบบมาตรฐาน (มีขีดล่าง เช่น ETH_USDT)"""
    try:
        clean_symbol = normalize_symbol(symbol)
        url = f"https://contract.mexc.com/api/v1/contract/kline/{clean_symbol}?interval={interval}"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            data = res["data"]
            if "close" in data and len(data["close"]) > 0:
                df = pd.DataFrame({
                    "close":
