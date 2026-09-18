"""
SUSHI/USDT - BULUT (GitHub Actions) IZLEME BOTU - Telegram Bildirimli
================================================================================
BU SCRIPT GERCEK ISLEM ACMAZ. GitHub Actions tarafindan periyodik olarak
(orn. her 15 dakikada bir) tetiklenir, TEK SEFERLIK bir kontrol yapar ve
sinyal varsa Telegram'a mesaj gonderip cikar. Sonsuz donguye GEREK YOKTUR,
cunku periyotu GitHub Actions'in zamanlanmis gorevi (schedule) yonetir.

Gerekli ortam degiskenleri (GitHub Secrets'tan gelir):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Durum (state) sushi_izleme_state.json dosyasinda tutulur; workflow bu
dosyayi her calistirmadan sonra repoya geri commit'ler, boylece bir sonraki
calistirmada acik sanal pozisyon hatirlanir.
"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import requests

CONFIG = {
    "SYMBOL": "SUSHIUSDT",
    "INTERVAL": "4h",
    "CANDLE_LIMIT": 200,

    "RESISTANCE_LOOKBACK": 10,
    "SUPPORT_LOOKBACK": 10,
    "RSI_PERIOD": 14,
    "RSI_MAX_ENTRY": 65,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "TP1_R": 1.5,
    "TP1_FRACTION": 0.5,
    "TP2_R": 2.0,

    "STATE_FILE": "sushi_izleme_state.json",
}


# ------------------------------------------------------------------------------------
# TELEGRAM BILDIRIMI
# ------------------------------------------------------------------------------------
def send_telegram(mesaj: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("UYARI: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ortam degiskeni yok, "
              "bildirim gonderilemedi (sadece konsola yazdiriliyor).")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": mesaj}, timeout=15)
        if not resp.ok:
            print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"Telegram gonderim hatasi: {exc}")


def uyar(mesaj: str):
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    satir = f"[{zaman}] {mesaj}"
    print(satir)
    send_telegram(satir)


# ------------------------------------------------------------------------------------
# VERI CEKME
# ------------------------------------------------------------------------------------
def fetch_recent_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    # NOT: api.binance.com bazi bulut sunucu bolgelerinden (orn. GitHub Actions'in
    # ABD merkezli sunuculari) 451 hatasiyla engellenebiliyor. data-api.binance.vision,
    # Binance'in ayni veriyi sunan, bu tur kisitlamaya takilmayan genel-veri adresidir.
    url = "https://data-api.binance.vision/api/v3/klines"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    rows = resp.json()

    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df[["open_time", "close_time", "open", "high", "low", "close", "volume"]]


# ------------------------------------------------------------------------------------
# INDIKATORLER
# ------------------------------------------------------------------------------------
def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df["close"].ewm(span=cfg["MACD_FAST"], adjust=False).mean()
    ema_slow = df["close"].ewm(span=cfg["MACD_SLOW"], adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=cfg["MACD_SIGNAL"], adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / cfg["RSI_PERIOD"], adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / cfg["RSI_PERIOD"], adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["resistance"] = df["high"].rolling(cfg["RESISTANCE_LOOKBACK"]).max().shift(1)
    df["support"] = df["low"].rolling(cfg["SUPPORT_LOOKBACK"]).min().shift(1)
    return df


# ------------------------------------------------------------------------------------
# DURUM (STATE)
# ------------------------------------------------------------------------------------
def load_state(cfg: dict) -> dict:
    if os.path.exists(cfg["STATE_FILE"]):
        with open(cfg["STATE_FILE"], "r", encoding="utf-8") as f:
            return json.load(f)
    return {"position": None}


def save_state(state: dict, cfg: dict):
    with open(cfg["STATE_FILE"], "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------------------------
# TEK KONTROL (GitHub Actions her tetiklendiginde bu calisir, sonra script biter)
# ------------------------------------------------------------------------------------
def check_once(cfg: dict, state: dict):
    df = fetch_recent_klines(cfg["SYMBOL"], cfg["INTERVAL"], cfg["CANDLE_LIMIT"])

    now = pd.Timestamp.now()
    if df.iloc[-1]["close_time"] > now:
        df = df.iloc[:-1]

    if len(df) < max(cfg["MACD_SLOW"], cfg["RESISTANCE_LOOKBACK"]) + 5:
        print("Yeterli mum verisi yok, atlaniyor.")
        return

    df = add_indicators(df, cfg)
    row = df.iloc[-1]
    position = state.get("position")

    if position is not None:
        if row["low"] <= position["stop"]:
            uyar(f"SUSHI: STOP-LOSS TETIKLENDI. Fiyat {position['stop']:.4f} seviyesine indi "
                 f"(Giris: {position['entry']:.4f}).")
            state["position"] = None

        elif (not position["tp1_done"]) and row["high"] >= position["tp1_price"]:
            uyar(f"SUSHI: TP1 TETIKLENDI ({position['tp1_price']:.4f}). Pozisyonun bir kismini "
                 f"kapatmayi degerlendir, stop basabasa (giris {position['entry']:.4f}) cekildi.")
            position["tp1_done"] = True
            position["stop"] = position["entry"]
            state["position"] = position

        elif row["high"] >= position["tp2_price"]:
            uyar(f"SUSHI: TP2 (FINAL) TETIKLENDI ({position['tp2_price']:.4f}). Kalan pozisyonu "
                 f"kapatmayi degerlendir.")
            state["position"] = None

        else:
            print(f"Acik sanal pozisyon devam ediyor. Guncel: {row['close']:.4f} | "
                  f"Stop: {position['stop']:.4f} | TP1: {position['tp1_price']:.4f} | "
                  f"TP2: {position['tp2_price']:.4f}")

    else:
        breakout = pd.notna(row["resistance"]) and row["close"] > row["resistance"]
        macd_bullish = (row["macd_hist"] > 0) and (row["macd"] > row["macd_signal"])
        rsi_ok = pd.notna(row["rsi"]) and row["rsi"] < cfg["RSI_MAX_ENTRY"]

        if breakout and macd_bullish and rsi_ok and pd.notna(row["support"]):
            entry = row["close"]
            stop = row["support"]
            risk = entry - stop
            new_position = {
                "entry_time": str(row["open_time"]),
                "entry": entry,
                "stop": stop,
                "tp1_price": entry + cfg["TP1_R"] * risk,
                "tp2_price": entry + cfg["TP2_R"] * risk,
                "tp1_done": False,
            }
            state["position"] = new_position
            uyar(f"SUSHI: GIRIS SINYALI (LONG). Fiyat {entry:.4f}'te direnci kirdi. "
                 f"Onerilen stop: {stop:.4f} | TP1: {new_position['tp1_price']:.4f} | "
                 f"TP2: {new_position['tp2_price']:.4f}")
        else:
            print(f"Sinyal yok. Guncel: {row['close']:.4f} | Direnc: {row['resistance']:.4f} | "
                  f"RSI: {row['rsi']:.1f} | MACD hist: {row['macd_hist']:.5f}")


def main():
    cfg = CONFIG

    if os.environ.get("TEST_MODE") == "true":
        uyar("SUSHI izleme botu: bu bir TEST mesajidir. Bu mesaji goruyorsan Telegram "
             "baglantisi dogru calisiyor demektir.")
        return

    state = load_state(cfg)
    try:
        check_once(cfg, state)
        save_state(state, cfg)
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
