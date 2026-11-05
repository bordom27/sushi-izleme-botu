"""
BTC kapsamli veri toplama (GitHub Actions'ta calisir). Cikti: arastirma_cikti/btc/*.csv.gz
Her kaynak bagimsiz; biri basarisiz olursa digerleri devam eder (log'a yazilir).
"""
from __future__ import annotations

import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

import veri

OUT = "arastirma_cikti/btc"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json"}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def kaydet(df, ad):
    df.to_csv(f"{OUT}/{ad}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi {ad}: {len(df)} satir, {df.iloc[0, 0] if len(df) else '-'} -> {df.iloc[-1, 0] if len(df) else '-'}")


def klines(symbol, interval, bas="2019-09-01", vadeli=True):
    ms = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[interval]
    start = int(pd.Timestamp(bas, tz="UTC").timestamp() * 1000)
    rows = []
    while True:
        if vadeli:
            d = veri._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "startTime": start, "limit": 1500}, veri.FAPI_URLS)
        else:
            d = veri._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "startTime": start, "limit": 1000})
        if not d:
            break
        rows.extend(d)
        if len(d) < (1500 if vadeli else 1000):
            break
        start = d[-1][0] + ms
        time.sleep(0.1)
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "x"])
    df = df.drop_duplicates("t")[["t", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq"]]
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    for k in ["o", "h", "l", "c", "v", "qv", "tb", "tq"]:
        df[k] = df[k].astype(float)
    return df[df.t < pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(ms, "ms")]


def uzun():
    """Haftalik/aylik analiz icin uzun gunluk gecmis: Binance spot (2017-08'den) + Coinbase (2015'ten)."""
    kaydet(klines("BTCUSDT", "1d", "2017-08-01", vadeli=False), "spot_1d_uzun")
    rows, bas = [], pd.Timestamp("2015-07-20")
    son = pd.Timestamp.utcnow().tz_localize(None)
    while bas < son:
        bit = min(bas + pd.Timedelta(days=300), son)
        r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                         params={"granularity": 86400, "start": bas.isoformat(), "end": bit.isoformat()}, headers=H, timeout=30)
        if r.ok:
            rows.extend(r.json())
        bas = bit
        time.sleep(0.5)
    df = pd.DataFrame(rows, columns=["t", "l", "h", "o", "c", "v"]).drop_duplicates("t")
    df["t"] = pd.to_datetime(df["t"], unit="s")
    kaydet(df.sort_values("t")[["t", "o", "h", "l", "c", "v"]], "coinbase_1d_uzun")


def adim(ad, f):
    try:
        f()
    except Exception as exc:
        log(f"HATA {ad}: {exc!r}")


def fiyatlar():
    for iv in ("15m", "1h", "4h", "1d"):
        kaydet(klines("BTCUSDT", iv), f"perp_{iv}")
    kaydet(klines("BTCUSDT", "1h", "2019-09-01", vadeli=False), "spot_1h")
    kaydet(klines("ETHUSDT", "1h"), "eth_perp_1h")


def funding():
    rows, start = [], int(pd.Timestamp("2019-09-01", tz="UTC").timestamp() * 1000)
    while True:
        d = veri._get("/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "startTime": start, "limit": 1000}, veri.FAPI_URLS)
        if not d:
            break
        rows.extend(d)
        if len(d) < 1000:
            break
        start = d[-1]["fundingTime"] + 1
    df = pd.DataFrame(rows)
    kaydet(pd.DataFrame({"t": pd.to_datetime(df.fundingTime, unit="ms"), "fr": df.fundingRate.astype(float)}), "funding")


def metrics():
    """data.binance.vision gunluk metrik dosyalari (5 dk): open interest, top trader / hesap long-short, taker oran."""
    gunler = [date(2020, 9, 1) + timedelta(days=i) for i in range((date.today() - date(2020, 9, 1)).days)]

    def al(g):
        u = f"https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{g:%Y-%m-%d}.zip"
        for _ in range(3):
            try:
                r = requests.get(u, timeout=30)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
            except Exception:
                time.sleep(2)
        return None

    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(al, gunler) if p is not None]
    df = pd.concat(parts, ignore_index=True)
    df = df.rename(columns={"create_time": "t"})
    df["t"] = pd.to_datetime(df["t"])
    df = df.drop(columns=[c for c in df.columns if c == "symbol"]).sort_values("t").drop_duplicates("t")
    kaydet(df, "metrics_5m")


def fng():
    d = requests.get("https://api.alternative.me/fng/?limit=0&format=json", headers=H, timeout=30).json()["data"]
    df = pd.DataFrame(d)
    df = pd.DataFrame({"t": pd.to_datetime(df.timestamp.astype(int), unit="s"), "fng": df.value.astype(int)}).sort_values("t")
    kaydet(df, "fng")


def coinbase():
    rows = []
    bas = pd.Timestamp("2019-09-01")
    son = pd.Timestamp.utcnow().tz_localize(None)
    while bas < son:
        bit = min(bas + pd.Timedelta(hours=300), son)
        for _ in range(4):
            try:
                r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                                 params={"granularity": 3600, "start": bas.isoformat(), "end": bit.isoformat()}, headers=H, timeout=30)
                if r.status_code == 429:
                    time.sleep(3)
                    continue
                r.raise_for_status()
                rows.extend(r.json())
                break
            except Exception:
                time.sleep(2)
        bas = bit
        time.sleep(0.35)
    df = pd.DataFrame(rows, columns=["t", "l", "h", "o", "c", "v"]).drop_duplicates("t")
    df["t"] = pd.to_datetime(df["t"], unit="s")
    kaydet(df.sort_values("t")[["t", "o", "h", "l", "c", "v"]], "coinbase_1h")


def stablecoin():
    d = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", headers=H, timeout=60).json()
    df = pd.DataFrame({"t": pd.to_datetime([int(x["date"]) for x in d], unit="s"),
                       "stable_usd": [x.get("totalCirculatingUSD", {}).get("peggedUSD", float("nan")) for x in d]})
    kaydet(df, "stablecoin")


def fred():
    out = None
    for sid in ("SP500", "NASDAQCOM", "VIXCLS", "DTWEXBGS", "DGS10", "T10Y2Y", "DFF", "DCOILWTICO"):
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers=H, timeout=60)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["t", sid]
            df["t"] = pd.to_datetime(df["t"])
            df[sid] = pd.to_numeric(df[sid], errors="coerce")
            out = df if out is None else out.merge(df, on="t", how="outer")
            log(f"fred {sid} {len(df)}")
        except Exception as exc:
            log(f"HATA fred {sid}: {exc!r}")
    kaydet(out.sort_values("t"), "makro")


def haber():
    """GDELT: 'bitcoin' haberlerinin gunluk tonu ve hacmi (aylik parcalar)."""
    parts = []
    bas = pd.Timestamp("2019-09-01")
    while bas < pd.Timestamp.utcnow().tz_localize(None):
        bit = bas + pd.DateOffset(months=1)
        for mod in ("timelinetone", "timelinevolraw"):
            try:
                r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                                 params={"query": "bitcoin", "mode": mod, "format": "csv",
                                         "startdatetime": bas.strftime("%Y%m%d%H%M%S"), "enddatetime": bit.strftime("%Y%m%d%H%M%S"),
                                         "timelinesmooth": 0}, headers=H, timeout=60)
                if r.ok and len(r.text) > 30:
                    df = pd.read_csv(io.StringIO(r.text))
                    df["mod"] = mod
                    parts.append(df)
            except Exception as exc:
                log(f"gdelt {bas:%Y-%m} {mod}: {exc!r}")
            time.sleep(6)
        bas = bit
    if parts:
        kaydet(pd.concat(parts, ignore_index=True), "haber_gdelt")


if __name__ == "__main__":
    import sys
    secim = sys.argv[1] if len(sys.argv) > 1 else "hepsi"
    isler = {"fiyat": fiyatlar, "funding": funding, "metrics": metrics, "fng": fng, "coinbase": coinbase,
             "stable": stablecoin, "fred": fred, "haber": haber, "uzun": uzun}
    for ad, f in isler.items():
        if secim in ("hepsi", ad) or (secim == "hizli" and ad not in ("metrics", "haber", "coinbase", "uzun")):
            adim(ad, f)
    open(f"{OUT}/log_{secim}.txt", "w").write("\n".join(LOG))
