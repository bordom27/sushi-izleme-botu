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
    # KRIPTO: coklu_varlik_backtest.py'nin ATR-bazli stop+trailing ile yapilan
    # 399 varlik taramasinda GERCEKTEN pozitif ve yeterli islem sayisina (8+)
    # sahip ciktigi dogrulanan liste (guncelleme: 20 Eylul 2026).
    "CRYPTO_SYMBOLS": [
        "JSTUSDT", "ALGOUSDT", "NEARUSDT", "KAITOUSDT", "DEXEUSDT", "TRXUSDT",
        "RAYUSDT", "SUSDT", "AVAUSDT", "CAKEUSDT", "ENAUSDT", "ALLOUSDT",
        "JTOUSDT", "ZAMAUSDT", "CUSDT", "CHZUSDT", "SKLUSDT", "ZENUSDT",
        "PYTHUSDT", "SOPHUSDT", "ETHFIUSDT", "ZECUSDT", "PHAUSDT", "MORPHOUSDT",
        "NILUSDT", "PLUMEUSDT", "XRPUSDT", "PEPEUSDT", "ARBUSDT", "MINAUSDT",
        "XTZUSDT", "APTUSDT", "DOTUSDT", "SKYUSDT", "HFTUSDT", "FUSDT",
        "AGLDUSDT", "NFPUSDT", "METUSDT", "CTSIUSDT", "ACEUSDT", "PROMUSDT",
        "TUSDT", "PAXGUSDT", "FILUSDT", "EPICUSDT", "GUNUSDT", "ZILUSDT",
        "BERAUSDT", "SAGAUSDT", "AAVEUSDT", "DASHUSDT",
    ],
    "CRYPTO_INTERVAL": "4h",
    "CRYPTO_CANDLE_LIMIT": 200,

    # HISSE: bu turda da hicbir ABD hissesi 8+ islemle esigi gecemedi - liste bos.
    "US_STOCKS": [],
    "BIST_STOCKS": [
        "EREGL.IS", "YKBNK.IS", "IZMDC.IS", "ICBCT.IS", "SARKY.IS", "NUGYO.IS",
        "INDES.IS", "ECILC.IS", "TUPRS.IS", "SISE.IS", "TTKOM.IS", "ALARK.IS",
        "KCHOL.IS", "PETKM.IS", "LOGO.IS", "ENKAI.IS", "ASTOR.IS",
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

    "USE_VOLUME_FILTER": True,
    "VOLUME_LOOKBACK": 20,
    "VOLUME_MULT": 1.2,
    "USE_TREND_FILTER": True,
    "TREND_EMA_LEN": 50,

    "STATE_FILE": "izleme_state.json",
    "REQUEST_DELAY": 0.35,   # ardisik istekler arasi bekleme (nazik olmak icin)

    # RISK YONETIMI (coklu_varlik_backtest.py ile ayni mantik)
    "ATR_PERIOD": 14,
    "USE_ATR_STOP": True,
    "ATR_STOP_MULT": 2.0,
    "USE_TRAILING_STOP": True,
    "TRAIL_ATR_MULT": 2.5,

    # ASIRI UZAMIS MUM FILTRESI: kirilim muminin (high-low) araligi ATR'nin bu
    # katindan buyukse, bu bir "tukenme/parabolik" mumu sayilir ve GIRIS YAPILMAZ.
    # Amac: devasa, aninda geri donme riski yuksek mumlara "kirildi" diye korku
    # icinde girmeyi onlemek.
    "USE_EXTENDED_CANDLE_FILTER": True,
    "MAX_CANDLE_RANGE_ATR": 2.0,

    # COOLDOWN: bir varlik stop olduktan sonra, ayni varliga tekrar giris
    # yapabilmek icin gecmesi gereken minimum mum sayisi. Amac: stop-loss
    # sonrasi ayni sikisik bolgede art arda giris/stop dongusune girmeyi
    # onlemek (kirilma hemen ardindan tekrar denemek yerine biraz "sogumasini"
    # beklemek).
    "COOLDOWN_BARS_AFTER_STOP": 3,

    # KORELASYON / CESITLILIK KONTROLU: ayni anda acik olabilecek pozisyon sayisi
    "MAX_CONCURRENT_TOTAL": 16,     # tum varliklarda toplamda en fazla bu kadar acik pozisyon
    "MAX_CONCURRENT_PER_KATEGORI": {
        "KRIPTO": 10, "ABD HISSE": 4, "BIST": 6,
    },

    # BILDIRIM KALITESI: varlik bazinda optimize edilmis (DENGELI SKOR - getiri VE
    # kazanma orani birlikte) parametrelerle elde edilen gecmis performans
    # (win_rate%, getiri%). Guncelleme: 20 Eylul 2026.
    "BACKTEST_ISTATISTIK": {
        "JSTUSDT": (73.7, 39.1), "NILUSDT": (60.5, 31.7), "ZECUSDT": (56.2, 32.8),
        "NEARUSDT": (54.5, 31.2), "PHAUSDT": (57.1, 28.9), "ZAMAUSDT": (61.3, 26.4),
        "METUSDT": (55.8, 26.9), "CHZUSDT": (48.8, 30.3), "ENAUSDT": (60.0, 23.7),
        "DEXEUSDT": (56.8, 24.3), "CUSDT": (56.8, 24.0), "KAITOUSDT": (58.8, 22.4),
        "ALGOUSDT": (65.0, 19.5), "DOTUSDT": (63.6, 19.8), "PAXGUSDT": (56.0, 22.3),
        "PROMUSDT": (50.0, 22.9), "TRXUSDT": (62.5, 18.2), "ARBUSDT": (53.7, 21.0),
        "SUSDT": (61.9, 17.4), "AVAUSDT": (46.2, 22.7), "CAKEUSDT": (56.7, 18.0),
        "SKLUSDT": (54.8, 17.1), "EPICUSDT": (50.0, 17.9), "ETHFIUSDT": (56.0, 14.7),
        "RAYUSDT": (53.1, 15.3), "SOPHUSDT": (51.3, 15.3), "MINAUSDT": (47.8, 16.3),
        "PLUMEUSDT": (57.1, 13.6), "ZENUSDT": (48.4, 15.3), "MORPHOUSDT": (51.5, 13.8),
        "ALLOUSDT": (61.5, 10.6), "GUNUSDT": (50.0, 12.6), "APTUSDT": (63.6, 9.7),
        "PYTHUSDT": (47.1, 11.6), "ACEUSDT": (62.5, 8.6), "ZILUSDT": (45.0, 11.6),
        "JTOUSDT": (43.8, 11.6), "BERAUSDT": (50.0, 9.8), "NFPUSDT": (42.1, 10.7),
        "PEPEUSDT": (62.5, 7.1), "HFTUSDT": (52.6, 8.5), "XRPUSDT": (47.6, 9.2),
        "AGLDUSDT": (54.5, 7.9), "SAGAUSDT": (34.2, 11.8), "FUSDT": (40.0, 9.4),
        "SKYUSDT": (40.7, 8.7), "XTZUSDT": (50.0, 7.0), "TUSDT": (44.4, 7.4),
        "FILUSDT": (50.0, 6.2), "DASHUSDT": (35.9, 6.8), "CTSIUSDT": (37.5, 5.2),
        "AAVEUSDT": (35.9, 4.9),
        "TUPRS.IS": (66.7, 18.4), "EREGL.IS": (55.6, 14.6), "IZMDC.IS": (77.8, 13.2),
        "PETKM.IS": (64.3, 12.8), "ENKAI.IS": (70.0, 11.5), "ECILC.IS": (60.0, 11.1),
        "ASTOR.IS": (54.5, 10.7), "YKBNK.IS": (62.5, 10.6), "ICBCT.IS": (56.2, 9.6),
        "INDES.IS": (45.5, 11.2), "SARKY.IS": (55.6, 8.8), "NUGYO.IS": (55.6, 7.1),
        "SISE.IS": (55.6, 4.9), "KCHOL.IS": (50.0, 4.0), "LOGO.IS": (44.4, 4.2),
        "TTKOM.IS": (50.0, 2.8), "ALARK.IS": (44.4, 1.2),
    },

    # VARLIK BAZINDA PARAMETRELER: her varligin kendi en iyi RSI/ATR-stop/TP2
    # kombinasyonu - DENGELI SKOR (getiri x kazanma orani) ile secildi, sadece
    # ham getiriye gore degil. Guncelleme: 20 Eylul 2026.
    "VARLIK_PARAMETRELERI": {
        "JSTUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 3.0},
        "ALGOUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "NEARUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "KAITOUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "DEXEUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "TRXUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "RAYUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "SUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "AVAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "CAKEUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ENAUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "ALLOUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "JTOUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "ZAMAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "CUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "CHZUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "SKLUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "ZENUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 2.0},
        "PYTHUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "SOPHUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ETHFIUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ZECUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "PHAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "MORPHOUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "NILUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "PLUMEUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "XRPUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "PEPEUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "ARBUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "MINAUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "XTZUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "APTUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "DOTUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "SKYUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "HFTUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "FUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "AGLDUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "NFPUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "METUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "CTSIUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 3.0},
        "ACEUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "PROMUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "TUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "PAXGUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "FILUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "EPICUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "GUNUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ZILUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "BERAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "SAGAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.5},
        "AAVEUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "DASHUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "EREGL.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 3.0},
        "YKBNK.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "IZMDC.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "ICBCT.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "SARKY.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 3.0},
        "NUGYO.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "INDES.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "ECILC.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "TUPRS.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "SISE.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "TTKOM.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "ALARK.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "KCHOL.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "PETKM.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "LOGO.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.5, "TP2_R": 2.0},
        "ENKAI.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "ASTOR.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
    },
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

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(cfg["ATR_PERIOD"]).mean().shift(1)

    df["vol_avg"] = df["volume"].rolling(cfg["VOLUME_LOOKBACK"]).mean().shift(1)
    df["trend_ema"] = df["close"].ewm(span=cfg["TREND_EMA_LEN"], adjust=False).mean()

    # ---------------- SINYAL GUCU SKORU (0-100) ----------------
    # Sabit sayilarla olcekleme yerine, her bileseni SON 100 BARIN kendi
    # arasindaki goreceli konumuna gore (rolling min-max) 0-100'e yayariz.
    # Boylece skor gercekten tum araligi kullanir, "hicbir zaman 75'i gecmiyor"
    # gibi kalibrasyon sorunlari olusmaz.
    pencere = 100
    min_periods = 20

    def _rolling_skor(seri):
        roll_min = seri.rolling(pencere, min_periods=min_periods).min()
        roll_max = seri.rolling(pencere, min_periods=min_periods).max()
        span = (roll_max - roll_min).replace(0, np.nan)
        skor = (seri - roll_min) / span * 100
        return skor.clip(0, 100)

    rsi_ters = cfg["RSI_MAX_ENTRY"] - df["rsi"]           # dusuk RSI = daha fazla "alan" = yuksek skor
    vol_orani = df["volume"] / df["vol_avg"].replace(0, np.nan)
    trend_mesafe = (df["close"] - df["trend_ema"]) / df["atr"].replace(0, np.nan)

    rsi_skor = _rolling_skor(rsi_ters)
    macd_skor = _rolling_skor(df["macd_hist"])
    hacim_skor = _rolling_skor(vol_orani)
    trend_skor = _rolling_skor(trend_mesafe)

    df["sinyal_gucu"] = (rsi_skor * 0.25 + macd_skor * 0.30 + hacim_skor * 0.25 + trend_skor * 0.20).round(1)
    df["sinyal_gucu"] = df["sinyal_gucu"].fillna(50.0)  # yeterli gecmis yoksa notr deger

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
# YARDIMCI: kategori bazinda acik pozisyon sayisi
# ------------------------------------------------------------------------------------

def acik_pozisyon_sayilari(state: dict) -> dict:
    positions = state.get("positions", {})
    sayilar = {"KRIPTO": 0, "ABD HISSE": 0, "BIST": 0, "TOPLAM": 0}
    for label, pos in positions.items():
        if pos is None:
            continue
        sayilar["TOPLAM"] += 1
        for kategori in ("KRIPTO", "ABD HISSE", "BIST"):
            if label.startswith(f"[{kategori}]"):
                sayilar[kategori] += 1
    return sayilar


def islem_logla(state: dict, label: str, sonuc: str, pnl_pct: float):
    log = state.setdefault("trade_log", [])
    log.append({
        "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "varlik": label,
        "sonuc": sonuc,
        "pnl_pct": round(pnl_pct, 2),
    })
    if len(log) > 500:   # dosya sonsuza kadar buyumesin
        state["trade_log"] = log[-500:]


# ------------------------------------------------------------------------------------
# TEK SEMBOL KONTROLU
# ------------------------------------------------------------------------------------
def check_symbol(symbol: str, kategori: str, df: pd.DataFrame, cfg: dict, state: dict):
    # VARLIK BAZINDA PARAMETRE: bu sembol icin ozel ayarlar varsa genel ayarlarin
    # uzerine yaz (RSI_MAX_ENTRY, ATR_STOP_MULT, TP2_R). Yoksa genel ayarlar kalir.
    ozel_parametreler = cfg.get("VARLIK_PARAMETRELERI", {}).get(symbol)
    if ozel_parametreler:
        cfg = {**cfg, **ozel_parametreler}

    label = f"[{kategori}] {symbol}"
    now = pd.Timestamp.now()
    if len(df) and df.iloc[-1]["close_time"] > now:
        df = df.iloc[:-1]

    if len(df) < max(cfg["MACD_SLOW"], cfg["RESISTANCE_LOOKBACK"], cfg["ATR_PERIOD"], cfg["TREND_EMA_LEN"]) + 5:
        return

    df = add_indicators(df, cfg)
    row = df.iloc[-1]
    positions = state.setdefault("positions", {})
    position = positions.get(label)

    # Giris mumunun KENDISINDE stop/TP kontrolu YAPILMAZ - kontrol bir sonraki
    # mumdan itibaren baslar (aksi halde giris kapanistan hesaplanir ama ayni
    # mumun dusugu zaten stop'un altinda olabilir, mantiksiz bir durum olusur).
    giris_mumunda_miyiz = (position is not None
                            and position.get("entry_time") == str(row["open_time"]))

    if position is not None:
        if giris_mumunda_miyiz:
            pass  # bu mumda henuz kontrol yapma, bir sonraki calistirmada devam et

        elif row["low"] <= position["stop"]:
            pnl_pct = (position["stop"] / position["entry"] - 1) * 100
            uyar(f"{label}: STOP-LOSS tetiklendi ({position['stop']:.4f}). "
                 f"Giris: {position['entry']:.4f} | Sonuc: %{pnl_pct:.2f}")
            islem_logla(state, label, "STOP", pnl_pct)
            positions[label] = None
            state.setdefault("son_stop", {})[label] = str(row["open_time"])

        elif (not position["tp1_done"]) and row["high"] >= position["tp1_price"]:
            uyar(f"{label}: TP1 tetiklendi ({position['tp1_price']:.4f}). "
                 f"Stop basabasa cekildi, trailing stop devreye girdi.")
            position["tp1_done"] = True
            position["stop"] = position["entry"]
            positions[label] = position

        elif row["high"] >= position["tp2_price"]:
            pnl_pct = (position["tp2_price"] / position["entry"] - 1) * 100
            uyar(f"{label}: TP2 (final) tetiklendi ({position['tp2_price']:.4f}). "
                 f"Sonuc: %{pnl_pct:.2f}")
            islem_logla(state, label, "TP2_FINAL", pnl_pct)
            positions[label] = None

        else:
            # TRAILING STOP: TP1 sonrasi, ATR bazli olarak stop'u yukari cek (sadece kilitler)
            if position["tp1_done"] and cfg["USE_TRAILING_STOP"] and pd.notna(row["atr"]):
                trail_candidate = row["close"] - cfg["TRAIL_ATR_MULT"] * row["atr"]
                if trail_candidate > position["stop"]:
                    position["stop"] = trail_candidate
                    positions[label] = position

    else:
        # KORELASYON KONTROLU: kategori ve toplam limitlerini asiyorsak yeni giris ACMA
        sayilar = acik_pozisyon_sayilari(state)
        kategori_limit = cfg["MAX_CONCURRENT_PER_KATEGORI"].get(kategori, 999)
        if sayilar["TOPLAM"] >= cfg["MAX_CONCURRENT_TOTAL"] or sayilar[kategori] >= kategori_limit:
            return

        # COOLDOWN KONTROLU: bu varlik yakin zamanda stop olduysa, belirli bir
        # mum sayisi gecmeden tekrar giris yapma (art arda whipsaw'i onler).
        son_stop_zamani = state.get("son_stop", {}).get(label)
        if son_stop_zamani is not None:
            interval_td = (pd.Timedelta(hours=4) if kategori == "KRIPTO"
                            else pd.Timedelta(days=1))
            cooldown_td = interval_td * cfg["COOLDOWN_BARS_AFTER_STOP"]
            if row["open_time"] - pd.Timestamp(son_stop_zamani) < cooldown_td:
                return  # cooldown suresi dolmadi, bu turda giris denenmez

        breakout = pd.notna(row["resistance"]) and row["close"] > row["resistance"]
        macd_bullish = (row["macd_hist"] > 0) and (row["macd"] > row["macd_signal"])
        rsi_ok = pd.notna(row["rsi"]) and row["rsi"] < cfg["RSI_MAX_ENTRY"]
        atr_ok = (not cfg["USE_ATR_STOP"]) or pd.notna(row["atr"])
        support_ok = cfg["USE_ATR_STOP"] or pd.notna(row["support"])

        if cfg["USE_VOLUME_FILTER"] and pd.notna(row["vol_avg"]):
            volume_ok = row["volume"] > row["vol_avg"] * cfg["VOLUME_MULT"]
        else:
            volume_ok = not cfg["USE_VOLUME_FILTER"]

        if cfg["USE_TREND_FILTER"] and pd.notna(row["trend_ema"]):
            trend_ok = row["close"] > row["trend_ema"]
        else:
            trend_ok = not cfg["USE_TREND_FILTER"]

        if cfg["USE_EXTENDED_CANDLE_FILTER"] and pd.notna(row["atr"]) and row["atr"] > 0:
            candle_range = row["high"] - row["low"]
            asiri_mum_degil = candle_range <= cfg["MAX_CANDLE_RANGE_ATR"] * row["atr"]
        else:
            asiri_mum_degil = True

        if (breakout and macd_bullish and rsi_ok and atr_ok and support_ok
                and volume_ok and trend_ok and asiri_mum_degil):
            entry = row["close"]
            stop = entry - cfg["ATR_STOP_MULT"] * row["atr"] if cfg["USE_ATR_STOP"] else row["support"]
            risk = entry - stop
            if risk > 0:
                tp2_r_etkin = max(cfg["TP2_R"], cfg["TP1_R"] + 0.5)  # TP2 her zaman TP1'den >=0.5R yukarida
                new_position = {
                    "entry_time": str(row["open_time"]),
                    "entry": entry,
                    "stop": stop,
                    "tp1_price": entry + cfg["TP1_R"] * risk,
                    "tp2_price": entry + tp2_r_etkin * risk,
                    "tp1_done": False,
                }
                positions[label] = new_position

                istat = cfg["BACKTEST_ISTATISTIK"].get(symbol)
                istat_metni = (f" | Gecmis backtest: %{istat[0]:.0f} kazanma, %{istat[1]:.1f} getiri"
                                if istat else " | Gecmis backtest verisi yok (dogrulanmamis)")
                guc_skoru = row["sinyal_gucu"]
                uyar(f"{label}: GIRIS SINYALI (LONG). Fiyat {entry:.4f}'te direnci kirdi. "
                     f"Sinyal gucu: {guc_skoru}/100 | "
                     f"Stop: {stop:.4f} | TP1: {new_position['tp1_price']:.4f} | "
                     f"TP2: {new_position['tp2_price']:.4f}{istat_metni}")


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
            check_symbol(symbol, "KRIPTO", df, cfg, state)
            taranan += 1
        except Exception as exc:
            print(f"{symbol} taranirken hata: {exc}")
            hatali += 1
        time.sleep(cfg["REQUEST_DELAY"])

    # --- HISSELER (ABD + BIST) ---
    tum_hisseler = [(s, "ABD HISSE") for s in cfg["US_STOCKS"]] + \
                   [(s, "BIST") for s in cfg["BIST_STOCKS"]]
    print(f"{len(tum_hisseler)} hisse taranacak.")
    for symbol, kategori in tum_hisseler:
        try:
            df = fetch_yahoo_klines(symbol, cfg["STOCK_INTERVAL"], cfg["STOCK_RANGE"])
            check_symbol(symbol, kategori, df, cfg, state)
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
