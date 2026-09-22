"""
OTOMATIK ALIM-SATIM BOTU - BINANCE SPOT TESTNET
================================================================================
!!! ONEMLI GUVENLIK NOTU !!!
Bu script sadece BINANCE SPOT TESTNET'te (sahte parayla) calisir. Gercek
Binance hesabinla HICBIR ILGISI YOKTUR. Asagidaki BASE_URL kontrolu, yanlislikla
gercek API'ye baglanmayi ENGELLEMEK icin var - bunu degistirmeden once cok
dikkatli ol ve ne yaptigini tam olarak bil.

Ne yapiyor:
  - 5 istatistiksel olarak guvenilir varligi (GUCLU/ORTA) tarar
  - Sinyal geldiginde GERCEK (testnet) MARKET BUY emri gonderir
  - Hemen ardindan OCO (One-Cancels-Other) emriyle stop-loss VE TP1 kar-al
    emrini AYNI ANDA borsaya yerlestirir - boylece pozisyon her zaman korunur
  - OCO emri BASARISIZ olursa, GUVENLIK ONLEMI olarak pozisyonu ANINDA
    MARKET SELL ile kapatir (korumasiz pozisyon birakmaz)
  - Her islem Telegram'a bildirilir

Kurulum:
  pip install python-binance requests --break-system-packages
  Ortam degiskenleri (environment variables) ayarlanmali:
    BINANCE_TESTNET_API_KEY
    BINANCE_TESTNET_API_SECRET
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
  ASLA bu anahtarlari kod icine yazma, ASLA baskasiyla paylasma.
"""

import os
import sys
import json
import time
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
except ImportError:
    print("HATA: python-binance kutuphanesi kurulu degil.")
    print("Calistir: pip install python-binance --break-system-packages")
    sys.exit(1)

# ------------------------------------------------------------------------------------
# GUVENLIK KONTROLU - bu script SADECE testnet ile calisir
# ------------------------------------------------------------------------------------
TESTNET_MODE = True   # BUNU DEGISTIRME - gercek paraya gecis ayri, bilincli bir adimdir

CONFIG = {
    "SYMBOLS": {
        "PAXGUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5, "KATEGORI": "GUCLU"},
        "PHAUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5, "KATEGORI": "ORTA"},
        "KAITOUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 2.0, "KATEGORI": "ORTA"},
        "JSTUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.0, "TP2_R": 1.5, "KATEGORI": "ORTA"},
        "TUSDT": {"RSI_MAX_ENTRY": 75, "ATR_STOP_MULT": 2.5, "TP2_R": 1.5, "KATEGORI": "ORTA"},
    },

    "USDT_PER_TRADE": 100.0,
    "INTERVAL": "4h",
    "CANDLE_LIMIT": 200,

    "RESISTANCE_LOOKBACK": 10,
    "RSI_PERIOD": 14,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "ATR_PERIOD": 14,
    "USE_VOLUME_FILTER": True,
    "VOLUME_LOOKBACK": 20,
    "VOLUME_MULT": 1.2,
    "USE_TREND_FILTER": True,
    "TREND_EMA_LEN": 50,
    "USE_EXTENDED_CANDLE_FILTER": True,
    "MAX_CANDLE_RANGE_ATR": 2.0,
    "COOLDOWN_BARS_AFTER_STOP": 3,
    "TP1_R": 1.5,

    "STATE_FILE": "otomatik_bot_state.json",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def uyar(mesaj: str):
    zaman = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{zaman} UTC] {mesaj}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": f"[OTOMATIK BOT-TESTNET] {mesaj}"},
                timeout=10,
            )
        except Exception as exc:
            print(f"UYARI: Telegram gonderilemedi: {exc}")
    else:
        print("UYARI: Telegram ortam degiskenleri yok, sadece konsola yaziliyor.")


def get_client() -> Client:
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET")
    if not api_key or not api_secret:
        uyar("HATA: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET ortam degiskenleri bulunamadi.")
        sys.exit(1)

    client = Client(api_key, api_secret, testnet=TESTNET_MODE)

    if not TESTNET_MODE:
        raise RuntimeError("GUVENLIK DURDURMASI: TESTNET_MODE False - bu script bunu desteklemez.")

    try:
        client.ping()
        acc = client.get_account()
        uyar(f"Binance TESTNET baglantisi basarili. Hesap durumu: {acc.get('accountType', '?')}")
    except Exception as exc:
        uyar(f"HATA: Binance testnet baglantisi kurulamadi: {exc}")
        sys.exit(1)

    return client


def state_yukle(cfg):
    if os.path.exists(cfg["STATE_FILE"]):
        with open(cfg["STATE_FILE"], "r") as f:
            return json.load(f)
    return {"positions": {}, "son_stop": {}}


def state_kaydet(cfg, state):
    with open(cfg["STATE_FILE"], "w") as f:
        json.dump(state, f, indent=2, default=str)


def fetch_klines(symbol, interval, limit):
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    rows = resp.json()
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]]


def add_indicators(df, cfg):
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
    df["vol_avg"] = df["volume"].rolling(cfg["VOLUME_LOOKBACK"]).mean().shift(1)
    df["trend_ema"] = df["close"].ewm(span=cfg["TREND_EMA_LEN"], adjust=False).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(cfg["ATR_PERIOD"]).mean().shift(1)
    return df


_symbol_info_cache = {}


def get_symbol_filters(client, symbol):
    if symbol in _symbol_info_cache:
        return _symbol_info_cache[symbol]
    info = client.get_symbol_info(symbol)
    filtreler = {f["filterType"]: f for f in info["filters"]}
    _symbol_info_cache[symbol] = filtreler
    return filtreler


def yuvarla_adim(deger, adim):
    if adim == 0:
        return deger, 8
    hassasiyet = int(round(-math.log10(adim)))
    return math.floor(deger / adim) * adim, hassasiyet


def miktar_formatla(client, symbol, miktar):
    filtreler = get_symbol_filters(client, symbol)
    step = float(filtreler["LOT_SIZE"]["stepSize"])
    yuvarlanan, hassasiyet = yuvarla_adim(miktar, step)
    return round(yuvarlanan, hassasiyet)


def fiyat_formatla(client, symbol, fiyat):
    filtreler = get_symbol_filters(client, symbol)
    tick = float(filtreler["PRICE_FILTER"]["tickSize"])
    yuvarlanan, hassasiyet = yuvarla_adim(fiyat, tick)
    return round(yuvarlanan, hassasiyet)


def emir_gonder_giris(client, cfg, symbol, entry_price_tahmini, stop, tp1):
    usdt_miktar = cfg["USDT_PER_TRADE"]
    ham_qty = usdt_miktar / entry_price_tahmini
    qty = miktar_formatla(client, symbol, ham_qty)

    if qty <= 0:
        uyar(f"{symbol}: HATA - hesaplanan miktar 0 veya negatif, islem acilmiyor.")
        return None

    try:
        emir = client.order_market_buy(symbol=symbol, quantity=qty)
    except (BinanceAPIException, BinanceOrderException) as exc:
        uyar(f"{symbol}: MARKET BUY BASARISIZ - {exc}")
        return None

    dolan_qty = float(emir.get("executedQty", qty))
    fills = emir.get("fills", [])
    if fills:
        toplam_deger = sum(float(f["price"]) * float(f["qty"]) for f in fills)
        gercek_entry = toplam_deger / dolan_qty if dolan_qty > 0 else entry_price_tahmini
    else:
        gercek_entry = entry_price_tahmini

    uyar(f"{symbol}: GIRIS emri DOLDU. Miktar: {dolan_qty}, Ortalama fiyat: {gercek_entry:.6f}")

    risk = gercek_entry - stop
    stop_gercek = gercek_entry - risk if risk > 0 else stop
    tp1_gercek = gercek_entry + cfg["TP1_R"] * risk if risk > 0 else tp1

    stop_fmt = fiyat_formatla(client, symbol, stop_gercek)
    stop_limit_fmt = fiyat_formatla(client, symbol, stop_gercek * 0.999)
    tp1_fmt = fiyat_formatla(client, symbol, tp1_gercek)
    satis_qty = miktar_formatla(client, symbol, dolan_qty)

    try:
        oco = client.create_oco_order(
            symbol=symbol,
            side="SELL",
            quantity=satis_qty,
            price=str(tp1_fmt),
            stopPrice=str(stop_fmt),
            stopLimitPrice=str(stop_limit_fmt),
            stopLimitTimeInForce="GTC",
        )
        uyar(f"{symbol}: KORUMA EMRI (OCO) yerlestirildi - Stop: {stop_fmt}, TP1: {tp1_fmt}")
        return {
            "entry": gercek_entry, "stop": stop_fmt, "tp1": tp1_fmt,
            "qty": dolan_qty, "oco_order_list_id": oco.get("orderListId"),
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
    except (BinanceAPIException, BinanceOrderException) as exc:
        uyar(f"{symbol}: !!! KRITIK - OCO emri BASARISIZ ({exc}). Pozisyon GUVENLIK ICIN aninda kapatiliyor.")
        try:
            client.order_market_sell(symbol=symbol, quantity=satis_qty)
            uyar(f"{symbol}: Pozisyon guvenlik nedeniyle basariyla kapatildi (korumasiz kalmadi).")
        except Exception as exc2:
            uyar(f"{symbol}: !!! COK KRITIK - GUVENLIK SATISI DA BASARISIZ OLDU: {exc2}. "
                 f"ELLE MUDAHALE GEREKIYOR - Binance testnet hesabini kontrol et!")
        return None


def acik_pozisyon_durumunu_kontrol_et(client, symbol, pozisyon):
    order_list_id = pozisyon.get("oco_order_list_id")
    if order_list_id is None:
        return None
    try:
        oco_durum = client.get_oco_order(orderListId=order_list_id)
        return oco_durum.get("listOrderStatus")
    except Exception as exc:
        uyar(f"{symbol}: OCO durumu sorgulanamadi: {exc}")
        return None


def sinyal_var_mi(df, cfg):
    row = df.iloc[-1]
    breakout = pd.notna(row["resistance"]) and row["close"] > row["resistance"]
    macd_bullish = (row["macd_hist"] > 0) and (row["macd"] > row["macd_signal"])
    rsi_ok = pd.notna(row["rsi"]) and row["rsi"] < cfg["RSI_MAX_ENTRY"]
    atr_ok = pd.notna(row["atr"]) and row["atr"] > 0
    volume_ok = (not cfg["USE_VOLUME_FILTER"]) or (
        pd.notna(row["vol_avg"]) and row["volume"] > row["vol_avg"] * cfg["VOLUME_MULT"])
    trend_ok = (not cfg["USE_TREND_FILTER"]) or (
        pd.notna(row["trend_ema"]) and row["close"] > row["trend_ema"])
    extended_ok = (not cfg["USE_EXTENDED_CANDLE_FILTER"]) or (not atr_ok) or (
        (row["high"] - row["low"]) <= cfg["MAX_CANDLE_RANGE_ATR"] * row["atr"])

    if breakout and macd_bullish and rsi_ok and atr_ok and volume_ok and trend_ok and extended_ok:
        entry = row["close"]
        stop = entry - cfg["SYMBOL_ATR_STOP_MULT"] * row["atr"]
        risk = entry - stop
        if risk > 0:
            tp1 = entry + cfg["TP1_R"] * risk
            return entry, stop, tp1
    return None


def check_symbol(client, symbol, sembol_cfg, cfg, state):
    df = fetch_klines(symbol, cfg["INTERVAL"], cfg["CANDLE_LIMIT"])
    if len(df) < 60:
        uyar(f"{symbol}: yeterli veri yok, atlaniyor.")
        return

    birlesik_cfg = dict(cfg)
    birlesik_cfg["RSI_MAX_ENTRY"] = sembol_cfg["RSI_MAX_ENTRY"]
    birlesik_cfg["SYMBOL_ATR_STOP_MULT"] = sembol_cfg["ATR_STOP_MULT"]
    df = add_indicators(df, birlesik_cfg)

    pozisyon = state["positions"].get(symbol)

    if pozisyon is not None:
        durum = acik_pozisyon_durumunu_kontrol_et(client, symbol, pozisyon)
        if durum == "ALL_DONE":
            uyar(f"{symbol}: Pozisyon kapandi (stop ya da TP1 tetiklendi).")
            state["positions"][symbol] = None
            state["son_stop"][symbol] = datetime.now(timezone.utc).isoformat()
        return

    son_stop = state["son_stop"].get(symbol)
    if son_stop:
        gecen = datetime.now(timezone.utc) - datetime.fromisoformat(son_stop)
        if gecen.total_seconds() < cfg["COOLDOWN_BARS_AFTER_STOP"] * 4 * 3600:
            return

    sonuc = sinyal_var_mi(df, birlesik_cfg)
    if sonuc is None:
        return

    entry_tahmin, stop, tp1 = sonuc
    uyar(f"{symbol}: SINYAL TESPIT EDILDI. Tahmini giris: {entry_tahmin:.6f}, "
         f"Stop: {stop:.6f}, TP1: {tp1:.6f}. GERCEK (testnet) emir gonderiliyor...")

    yeni_pozisyon = emir_gonder_giris(client, cfg, symbol, entry_tahmin, stop, tp1)
    if yeni_pozisyon:
        state["positions"][symbol] = yeni_pozisyon


def main():
    cfg = CONFIG
    uyar("=" * 60)
    uyar(f"OTOMATIK BOT BASLADI (TESTNET_MODE={TESTNET_MODE}) - {len(cfg['SYMBOLS'])} varlik taranacak")
    uyar("=" * 60)

    client = get_client()
    state = state_yukle(cfg)

    for symbol, sembol_cfg in cfg["SYMBOLS"].items():
        try:
            check_symbol(client, symbol, sembol_cfg, cfg, state)
        except Exception as exc:
            uyar(f"{symbol}: BEKLENMEYEN HATA - {exc}")
        time.sleep(1)

    state_kaydet(cfg, state)
    uyar("Tarama tamamlandi.")


if __name__ == "__main__":
    main()
