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


def dvol():
    """Deribit BTC volatilite endeksi (opsiyon beklenen oynaklik), saatlik, 2021-03'ten."""
    rows = []
    bas = int(pd.Timestamp("2021-03-01", tz="UTC").timestamp() * 1000)
    son = int(pd.Timestamp.utcnow().timestamp() * 1000)
    while bas < son:
        bit = min(bas + 1000 * 3600 * 1000, son)
        r = requests.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                         params={"currency": "BTC", "start_timestamp": bas, "end_timestamp": bit, "resolution": "3600"},
                         headers=H, timeout=30)
        r.raise_for_status()
        d = r.json()["result"]["data"]
        rows.extend(d)
        bas = bit
        time.sleep(0.3)
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c"]).drop_duplicates("t")
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    kaydet(df.sort_values("t")[["t", "c"]].rename(columns={"c": "dvol"}), "dvol")


def zincir():
    """blockchain.com zincir ustu gunluk seriler."""
    out = None
    for ad in ("hash-rate", "n-transactions", "n-unique-addresses", "transaction-fees-usd", "miners-revenue",
               "estimated-transaction-volume-usd", "mempool-size", "difficulty"):
        try:
            r = requests.get(f"https://api.blockchain.info/charts/{ad}", params={"timespan": "all", "format": "json", "sampled": "false"},
                             headers=H, timeout=60)
            r.raise_for_status()
            v = r.json()["values"]
            df = pd.DataFrame(v)
            df = pd.DataFrame({"t": pd.to_datetime(df.x, unit="s"), ad.replace("-", "_"): df.y})
            df = df.groupby(df.t.dt.floor("1D")).last().reset_index(drop=True)
            out = df if out is None else out.merge(df, on="t", how="outer")
            log(f"zincir {ad} {len(df)}")
        except Exception as exc:
            log(f"HATA zincir {ad}: {exc!r}")
        time.sleep(1)
    kaydet(out.sort_values("t"), "zincir")


def kimchi():
    """Upbit KRW-BTC gunluk + FRED USD/KRW -> Kore primi."""
    rows, to = [], None
    for _ in range(20):
        prm = {"market": "KRW-BTC", "count": 200}
        if to:
            prm["to"] = to
        r = requests.get("https://api.upbit.com/v1/candles/days", params=prm, headers=H, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not d:
            break
        rows.extend(d)
        to = d[-1]["candle_date_time_utc"].replace("T", " ")
        if pd.Timestamp(to) < pd.Timestamp("2019-06-01"):
            break
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    df = pd.DataFrame({"t": pd.to_datetime(df.candle_date_time_utc), "krw_btc": df.trade_price.astype(float)}).drop_duplicates("t")
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS", headers=H, timeout=60)
    fx = pd.read_csv(io.StringIO(r.text))
    fx.columns = ["t", "usdkrw"]
    fx["t"] = pd.to_datetime(fx.t)
    fx["usdkrw"] = pd.to_numeric(fx.usdkrw, errors="coerce")
    df = df.sort_values("t").merge(fx, on="t", how="left")
    df["usdkrw"] = df.usdkrw.ffill()
    kaydet(df, "kimchi")


def piyasalar():
    """Binance BTCDOM vadeli (BTC dominansi) + Yahoo: CME BTC vadeli, altin, dolar endeksi, MSTR."""
    try:
        kaydet(klines("BTCDOMUSDT", "1h", "2021-01-01"), "btcdom_1h")
    except Exception as exc:
        log(f"HATA btcdom: {exc!r}")
    out = None
    for sym, ad in (("BTC=F", "cme"), ("GC=F", "altin"), ("DX-Y.NYB", "dxy"), ("MSTR", "mstr"), ("^GSPC", "spx_y")):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": "1d", "range": "10y"}, headers=H, timeout=60)
            r.raise_for_status()
            j = r.json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            df = pd.DataFrame({"t": pd.to_datetime(j["timestamp"], unit="s").normalize(), f"{ad}_o": q["open"], f"{ad}_c": q["close"]})
            out = df if out is None else out.merge(df, on="t", how="outer")
            log(f"yahoo {sym} {len(df)}")
        except Exception as exc:
            log(f"HATA yahoo {sym}: {exc!r}")
        time.sleep(1)
    if out is not None:
        kaydet(out.sort_values("t"), "piyasalar")


def petrol():
    out = None
    for sym, ad in (("CL=F", "wti"), ("BZ=F", "brent")):
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "1d", "range": "max"},
                         headers=H, timeout=60)
        r.raise_for_status()
        j = r.json()["chart"]["result"][0]
        q = j["indicators"]["quote"][0]
        df = pd.DataFrame({"t": pd.to_datetime(j["timestamp"], unit="s").normalize(), ad: q["close"]})
        out = df if out is None else out.merge(df, on="t", how="outer")
        log(f"yahoo {sym} {len(df)}")
    kaydet(out.sort_values("t"), "petrol")


def eski():
    """2015-2019: Coinbase BTC-USD saatlik + BitMEX XBTUSD funding (2016+)."""
    rows = []
    bas = pd.Timestamp("2015-07-20")
    son = pd.Timestamp("2019-10-01")
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
    kaydet(df.sort_values("t")[["t", "o", "h", "l", "c", "v"]], "coinbase_1h_eski")
    fr, start = [], "2016-05-01"
    while True:
        r = requests.get("https://www.bitmex.com/api/v1/funding", params={"symbol": "XBTUSD", "count": 500, "startTime": start,
                                                                          "reverse": "false"}, headers=H, timeout=60)
        if r.status_code == 429:
            time.sleep(10)
            continue
        r.raise_for_status()
        d = r.json()
        if not d:
            break
        fr.extend(d)
        if len(d) < 500:
            break
        start = (pd.Timestamp(d[-1]["timestamp"]) + pd.Timedelta("1s")).isoformat()
        time.sleep(1.2)
    df = pd.DataFrame(fr)
    kaydet(pd.DataFrame({"t": pd.to_datetime(df.timestamp).dt.tz_localize(None), "fr": df.fundingRate.astype(float)}), "bitmex_funding")


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
             "stable": stablecoin, "fred": fred, "haber": haber, "uzun": uzun, "dvol": dvol, "zincir": zincir, "kimchi": kimchi, "piyasa": piyasalar, "petrol": petrol, "eski": eski}
    for ad, f in isler.items():
        if (secim in ("hepsi", ad) or (secim == "hizli" and ad in ("fiyat", "funding", "fng", "stable", "fred"))
                or (secim == "ek" and ad in ("dvol", "zincir", "kimchi", "piyasa"))):
            adim(ad, f)
    open(f"{OUT}/log_{secim}.txt", "w").write("\n".join(LOG))
