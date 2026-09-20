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

    # KORELASYON / CESITLILIK KONTROLU: ayni anda acik olabilecek pozisyon sayisi
    "MAX_CONCURRENT_TOTAL": 16,     # tum varliklarda toplamda en fazla bu kadar acik pozisyon
    "MAX_CONCURRENT_PER_KATEGORI": {
        "KRIPTO": 10, "ABD HISSE": 4, "BIST": 6,
    },

    # BILDIRIM KALITESI: varlik bazinda optimize edilmis parametrelerle elde
    # edilen gecmis performans (win_rate%, getiri%). Guncelleme: 19 Eylul 2026,
    # varlik_bazinda_optimizasyon.py sonucu.
    "BACKTEST_ISTATISTIK": {
        "ZECUSDT": (57.6, 34.9), "NEARUSDT": (49.0, 32.1), "ZAMAUSDT": (61.3, 26.4),
        "SUSDT": (40.0, 25.6), "ENAUSDT": (44.2, 24.9), "ARBUSDT": (44.2, 24.5),
        "CUSDT": (56.8, 24.0), "PAXGUSDT": (48.9, 24.0), "DOTUSDT": (44.4, 22.1),
        "TRXUSDT": (41.9, 21.7), "ESPUSDT": (41.9, 21.3), "CAKEUSDT": (54.8, 16.1),
        "ZENUSDT": (39.4, 15.9), "RAYUSDT": (53.1, 15.3), "ETHFIUSDT": (56.0, 14.7),
        "MORPHOUSDT": (51.5, 13.8), "SAGAUSDT": (34.2, 10.6), "XRPUSDT": (40.0, 10.6),
        "APTUSDT": (63.6, 9.7), "FUSDT": (40.0, 9.4), "XTZUSDT": (38.1, 8.6),
        "DASHUSDT": (36.8, 8.5), "PEPEUSDT": (48.1, 7.3), "FILUSDT": (50.0, 6.2),
        "AAVEUSDT": (35.9, 4.9),
        "TUPRS.IS": (66.7, 18.4), "EREGL.IS": (55.6, 14.6), "PETKM.IS": (41.7, 14.5),
        "ENKAI.IS": (70.0, 11.5), "ECILC.IS": (60.0, 11.1), "ASTOR.IS": (54.5, 10.7),
        "YKBNK.IS": (62.5, 10.6), "SISE.IS": (33.3, 6.2), "KCHOL.IS": (30.8, 5.9),
        "TTKOM.IS": (50.0, 2.8), "ALARK.IS": (25.0, 2.0),

        # 20 Eylul 2026'da genisletilen taramada eklenen yeni varliklar
        # (henuz varlik bazinda optimize edilmedi, genel parametrelerle sonuc):
        "JSTUSDT": (78.9, 35.7), "ALGOUSDT": (47.6, 21.1), "KAITOUSDT": (52.6, 18.6),
        "DEXEUSDT": (61.5, 15.1), "AVAUSDT": (43.5, 11.4), "ALLOUSDT": (43.8, 10.0),
        "JTOUSDT": (44.0, 9.9), "CHZUSDT": (45.0, 8.9), "SKLUSDT": (38.1, 8.7),
        "PYTHUSDT": (46.4, 7.8), "SOPHUSDT": (36.8, 7.5), "IZMDC.IS": (55.6, 6.9),
        "PHAUSDT": (40.0, 6.0), "NILUSDT": (41.7, 5.8), "PLUMEUSDT": (40.0, 5.5),
        "ICBCT.IS": (30.0, 5.0), "MINAUSDT": (40.0, 4.7), "SARKY.IS": (50.0, 4.3),
        "NUGYO.IS": (50.0, 4.2), "INDES.IS": (50.0, 4.0), "SKYUSDT": (38.5, 3.9),
        "HFTUSDT": (41.2, 3.9), "AGLDUSDT": (38.1, 3.1), "NFPUSDT": (40.0, 2.9),
        "METUSDT": (36.0, 2.7), "CTSIUSDT": (37.5, 2.5), "ACEUSDT": (36.8, 2.2),
        "PROMUSDT": (42.9, 2.0), "TUSDT": (41.7, 1.9), "EPICUSDT": (38.5, 1.2),
        "LOGO.IS": (40.0, 1.1), "GUNUSDT": (31.2, 0.4), "ZILUSDT": (35.0, 0.4),
        "BERAUSDT": (35.7, 0.3),
    },

    # VARLIK BAZINDA PARAMETRELER: her varligin kendi en iyi RSI/ATR-stop/TP2
    # kombinasyonu (varlik_bazinda_optimizasyon.py sonucu, 19 Eylul 2026).
    # Burada olmayan bir sembol icin asagidaki genel RSI_MAX_ENTRY/ATR_STOP_MULT/
    # TP2_R degerleri (varsayilan) kullanilir.
    "VARLIK_PARAMETRELERI": {
        "ZECUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "NEARUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "ZAMAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "SUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.5},
        "ENAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "ARBUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "CUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "PAXGUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "DOTUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "TRXUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "ESPUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "CAKEUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ZENUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "RAYUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "ETHFIUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "MORPHOUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "SAGAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.5},
        "XRPUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "APTUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "FUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "XTZUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 2.5},
        "DASHUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
        "PEPEUSDT": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5},
        "FILUSDT": {"RSI_MAX_ENTRY": 60, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "AAVEUSDT": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "TUPRS.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.0},
        "EREGL.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 3.0},
        "PETKM.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "ENKAI.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5},
        "ECILC.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 1.5},
        "ASTOR.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 3.0},
        "YKBNK.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "SISE.IS": {"RSI_MAX_ENTRY": 70, "ATR_STOP_MULT": 1.5, "TP2_R": 3.0},
        "KCHOL.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 1.5, "TP2_R": 2.5},
        "TTKOM.IS": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 2.0},
        "ALARK.IS": {"RSI_MAX_ENTRY": 65, "ATR_STOP_MULT": 2.0, "TP2_R": 2.5},
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

    if position is not None:
        if row["low"] <= position["stop"]:
            pnl_pct = (position["stop"] / position["entry"] - 1) * 100
            uyar(f"{label}: STOP-LOSS tetiklendi ({position['stop']:.4f}). "
                 f"Giris: {position['entry']:.4f} | Sonuc: %{pnl_pct:.2f}")
            islem_logla(state, label, "STOP", pnl_pct)
            positions[label] = None

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

        if breakout and macd_bullish and rsi_ok and atr_ok and support_ok and volume_ok and trend_ok:
            entry = row["close"]
            stop = entry - cfg["ATR_STOP_MULT"] * row["atr"] if cfg["USE_ATR_STOP"] else row["support"]
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

                istat = cfg["BACKTEST_ISTATISTIK"].get(symbol)
                istat_metni = (f" | Gecmis backtest: %{istat[0]:.0f} kazanma, %{istat[1]:.1f} getiri"
                                if istat else " | Gecmis backtest verisi yok (dogrulanmamis)")
                uyar(f"{label}: GIRIS SINYALI (LONG). Fiyat {entry:.4f}'te direnci kirdi. "
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
