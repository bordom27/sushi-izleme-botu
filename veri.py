"""Binance spot mum verisi (sayfalama ile) - bot ve backtest ortak kullanir."""

from __future__ import annotations

import time

import pandas as pd
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
BASE_URLS = ["https://data-api.binance.vision", "https://api.binance.com"]
ARALIK_MS = {"4h": 4 * 3600_000, "1d": 86400_000, "1w": 7 * 86400_000}


def _get(path: str, params: dict):
    son_hata = None
    for base in BASE_URLS:
        for deneme in range(3):
            try:
                r = requests.get(base + path, params=params, headers=HEADERS, timeout=20)
                if r.status_code == 429:
                    time.sleep(2 + deneme * 3)
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # ag hatasi -> tekrar dene / diger adres
                son_hata = exc
                time.sleep(1 + deneme)
    raise RuntimeError(f"Binance istegi basarisiz: {path} {params} ({son_hata})")


def mumlar(symbol: str, interval: str, baslangic: str | pd.Timestamp, sadece_kapanmis: bool = True) -> pd.DataFrame:
    """baslangic tarihinden bugune tum mumlar (sayfa sayfa, 1000'er)."""
    ts = pd.Timestamp(baslangic)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    start_ms = int(ts.timestamp() * 1000)
    rows = []
    while True:
        data = _get("/api/v3/klines", {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": 1000})
        if not data:
            break
        rows.extend(data)
        if len(data) < 1000:
            break
        start_ms = data[-1][0] + ARALIK_MS.get(interval, 1)
        time.sleep(0.15)
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return pd.DataFrame(columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("open_time")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df = df[["open_time", "close_time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    if sadece_kapanmis:
        simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
        df = df[df["close_time"] < simdi].reset_index(drop=True)
    return df
