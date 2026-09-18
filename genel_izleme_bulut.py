"""
GENEL IZLEME BOTU - Kripto (Binance) + Hisse (Yahoo Finance) - Telegram Bildirimli
================================================================================
BU SCRIPT GERCEK ISLEM ACMAZ. GitHub Actions tarafindan periyodik tetiklenir,
asagidaki listelerdeki TUM varliklari tek tek tarar, her biri icin ayni
kirilim + MACD + RSI mantigini uygular ve sinyal varsa Telegram'a mesaj gonderir.

ONEMLI UYARI: Bu strateji sadece SUSHI/USDT 4 saatlik grafikte backtest edildi.
Diger kripto ve hisselerde ayni parametrelerle calismasi bir varsayimdir,
ayrica dogrulanmamistir - deneysel kabul et.

Gerekli ortam degiskenleri (GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""

import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests

# ------------------------------------------------------------------------------------
# AYARLAR
# ------------------------------------------------------------------------------------
CONFIG = {
    # KRIPTO: coklu_varlik_backtest.py'nin genisletilmis (160 varlik) taramasinda
    # GERCEKTEN pozitif ve yeterli islem sayisina (8+) sahip ciktigi dogrulanan liste.
    "CRYPTO_SYMBOLS": [
        "ZECUSDT", "RAYUSDT", "DASHUSDT", "REZUSDT", "ZAMAUSDT", "TRXUSDT",
        "PAXGUSDT", "ETHUSDT", "BNBUSDT", "DOTUSDT", "ENAUSDT", "CAKEUSDT",
        "BTCUSDT", "AVAUSDT", "PUMPUSDT", "SPCXBUSDT", "LINKUSDT",
    ],
    "CRYPTO_INTERVAL": "4h",
    "CRYPTO_CANDLE_LIMIT": 200,

    # HISSE: ayni sekilde dogrulanmis liste.
    "US_STOCKS": ["CSCO", "GS", "ABNB", "UPS", "GE", "INTC"],
    "BIST_STOCKS": [
        "PETKM.IS", "KRDMD.IS", "TOASO.IS", "HALKB.IS", "YKBNK.IS", "AKSA.IS",
        "ODAS.IS", "SASA.IS", "BERA.IS", "GESAN.IS", "SISE.IS", "MGROS.IS",
    ],
    "STOCK_INTERVAL": "1d",       # hisseler icin gunluk mum
    "STOCK_RANGE": "2y",          # yeterli gecmis veri icin

    # STRATEJI PARAMETRELERI (SUSHI backtest'inden - digerlerinde dogrulanmadi)
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

    "STATE_FILE": "izleme_state.json",
    "REQUEST_DELAY": 0.35,   # ardisik istekler arasi bekleme (nazik olmak icin)
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


# ------------------------------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------------------------------
def send_telegram(mesaj: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("UYARI: Telegram ortam degiskenleri yok, sadece konsola yaziliyor.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": mesaj}, timeout=15)
        if not resp.ok:
            print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"Telegram gonderim hatasi: {exc}")


def uyar(mesaj: str):
    satir = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mesaj}"
    print(satir)
    send_telegram(satir)


# ------------------------------------------------------------------------------------
# BINANCE: en yuksek hacimli N pariteyi bul
# ------------------------------------------------------------------------------------
def get_top_binance_symbols(n: int) -> list:
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"Binance hacim listesi alinamadi: {exc}. Sabit bir yedek liste kullanilacak.")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

    haric = ("UP", "DOWN", "BULL", "BEAR")
    stablecoin_ciftleri = (
        "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "RLUSDUSDT",
        "USD1USDT", "USDPUSDT", "PYUSDUSDT", "EURUSDT", "GBPUSDT",
    )
    adaylar = [
        d for d in data
        if d["symbol"].endswith("USDT")
        and not any(tag in d["symbol"] for tag in haric)
        and d["symbol"] not in stablecoin_ciftleri
        and not d["symbol"].startswith("U")  # UUSDT, USD1USDT gibi belirsiz/stabil coinlere karsi ekstra guvenlik
    ]
    adaylar.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [d["symbol"] for d in adaylar[:n]]


def fetch_binance_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
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
# YAHOO FINANCE: hisse verisi
# ------------------------------------------------------------------------------------
def fetch_yahoo_klines(symbol: str, interval: str, range_: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"{symbol} icin veri bulunamadi (Yahoo bos donus verdi).")

    r = result[0]
    timestamps = r.get("timestamp")
    if not timestamps:
        raise ValueError(f"{symbol} icin zaman serisi bos.")

    quote = r["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open_time": pd.to_datetime(timestamps, unit="s"),
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["close"],
        "volume": quote["volume"],
    })
    df["close_time"] = df["open_time"]  # gunluk veride ayrim onemli degil
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df[["open_time", "close_time", "open", "high", "low", "close", "volume"]]


# ------------------------------------------------------------------------------------
# INDIKATORLER (ortak)
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
# DURUM (her sembol icin ayri tutulur)
# ------------------------------------------------------------------------------------
def load_state(cfg: dict) -> dict:
    if os.path.exists(cfg["STATE_FILE"]):
        with open(cfg["STATE_FILE"], "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}}


def save_state(state: dict, cfg: dict):
    with open(cfg["STATE_FILE"], "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------------------------
# TEK SEMBOL KONTROLU
# ------------------------------------------------------------------------------------
def check_symbol(label: str, df: pd.DataFrame, cfg: dict, state: dict):
    now = pd.Timestamp.now()
    if len(df) and df.iloc[-1]["close_time"] > now:
        df = df.iloc[:-1]

    if len(df) < max(cfg["MACD_SLOW"], cfg["RESISTANCE_LOOKBACK"]) + 5:
        return

    df = add_indicators(df, cfg)
    row = df.iloc[-1]
    positions = state.setdefault("positions", {})
    position = positions.get(label)

    if position is not None:
        if row["low"] <= position["stop"]:
            uyar(f"{label}: STOP-LOSS tetiklendi ({position['stop']:.4f}). "
                 f"Giris: {position['entry']:.4f}")
            positions[label] = None

        elif (not position["tp1_done"]) and row["high"] >= position["tp1_price"]:
            uyar(f"{label}: TP1 tetiklendi ({position['tp1_price']:.4f}). "
                 f"Stop basabasa cekildi.")
            position["tp1_done"] = True
            position["stop"] = position["entry"]
            positions[label] = position

        elif row["high"] >= position["tp2_price"]:
            uyar(f"{label}: TP2 (final) tetiklendi ({position['tp2_price']:.4f}).")
            positions[label] = None

    else:
        breakout = pd.notna(row["resistance"]) and row["close"] > row["resistance"]
        macd_bullish = (row["macd_hist"] > 0) and (row["macd"] > row["macd_signal"])
        rsi_ok = pd.notna(row["rsi"]) and row["rsi"] < cfg["RSI_MAX_ENTRY"]

        if breakout and macd_bullish and rsi_ok and pd.notna(row["support"]):
            entry = row["close"]
            stop = row["support"]
            risk = entry - stop
            if risk > 0:
                new_position = {
                    "entry_time": str(row["open_time"]),
                    "entry": entry,
                    "stop": stop,
                    "tp1_price": entry + cfg["TP1_R"] * risk,
                    "tp2_price": entry + cfg["TP2_R"] * risk,
                    "tp1_done": False,
                }
                positions[label] = new_position
                uyar(f"{label}: GIRIS SINYALI (LONG). Fiyat {entry:.4f}'te direnci kirdi. "
                     f"Stop: {stop:.4f} | TP1: {new_position['tp1_price']:.4f} | "
                     f"TP2: {new_position['tp2_price']:.4f}")


# ------------------------------------------------------------------------------------
# ANA CALISTIRMA
# ------------------------------------------------------------------------------------
def main():
    cfg = CONFIG
    state = load_state(cfg)
    taranan = 0
    hatali = 0

    # --- KRIPTO (dogrulanmis sabit liste) ---
    crypto_symbols = cfg["CRYPTO_SYMBOLS"]
    print(f"{len(crypto_symbols)} kripto parite taranacak: {crypto_symbols}")
    for symbol in crypto_symbols:
        try:
            df = fetch_binance_klines(symbol, cfg["CRYPTO_INTERVAL"], cfg["CRYPTO_CANDLE_LIMIT"])
            check_symbol(f"[KRIPTO] {symbol}", df, cfg, state)
            taranan += 1
        except Exception as exc:
            print(f"{symbol} taranirken hata: {exc}")
            hatali += 1
        time.sleep(cfg["REQUEST_DELAY"])

    # --- HISSELER (ABD + BIST) ---
    tum_hisseler = [(s, "[ABD HISSE]") for s in cfg["US_STOCKS"]] + \
                   [(s, "[BIST]") for s in cfg["BIST_STOCKS"]]
    print(f"{len(tum_hisseler)} hisse taranacak.")
    for symbol, etiket in tum_hisseler:
        try:
            df = fetch_yahoo_klines(symbol, cfg["STOCK_INTERVAL"], cfg["STOCK_RANGE"])
            check_symbol(f"{etiket} {symbol}", df, cfg, state)
            taranan += 1
        except Exception as exc:
            print(f"{symbol} taranirken hata: {exc}")
            hatali += 1
        time.sleep(cfg["REQUEST_DELAY"])

    save_state(state, cfg)
    print(f"\nTarama tamamlandi. Basarili: {taranan} | Hatali: {hatali}")


if __name__ == "__main__":
    if os.environ.get("TEST_MODE") == "true":
        uyar("Genel izleme botu: bu bir TEST mesajidir. Telegram baglantisi calisiyor.")
        sys.exit(0)
    main()
