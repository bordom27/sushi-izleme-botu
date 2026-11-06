"""
K69 SHORT icin eski veri (GitHub Actions'ta). Vadeli veri 2019-09'da basladigi icin daha eski donem spot borsalardan:
  binance <parca> <toplam> : Binance spot 4s (data.binance.vision aylik arsiv), USDT ve BTC paritelerinin hepsi
                              (delist dahil), 2017-07 -> 2020-12. BTC paritesi yerelde BTCUSDT ile dolara cevrilir.
  bitfinex                 : Bitfinex USD pariteleri 4s, 2013 ->
  poloniex                 : Poloniex 4s (eski public API, 2014 ->) - erisim denemesi
Cikti: arastirma_cikti/eski/<kaynak>[_parca].csv.gz  (symbol, quote, t[saniye], o, h, l, c, v[baz birim])
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

OUT = "arastirma_cikti/eski"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (research script)"}
LOG = []
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def s3_liste(prefix, dizin=True):
    out, marker = [], ""
    while True:
        r = requests.get(S3, params={"delimiter": "/", "prefix": prefix, "marker": marker}, headers=H, timeout=60)
        r.raise_for_status()
        x = r.text
        if dizin:
            out += re.findall(r"<Prefix>([^<]+)</Prefix>", x)
        else:
            out += re.findall(r"<Key>([^<]+)</Key>", x)
        if "<IsTruncated>true</IsTruncated>" not in x:
            break
        nm = re.findall(r"<NextMarker>([^<]+)</NextMarker>", x)
        marker = nm[0] if nm else (out[-1] if out else "")
    return [p for p in out if p != prefix]


def binance(parca, toplam):
    dirs = s3_liste("data/spot/monthly/klines/")
    syms = sorted({d.rstrip("/").split("/")[-1] for d in dirs})
    syms = [s for s in syms if s.endswith("USDT") or s.endswith("BTC")]
    syms = [s for i, s in enumerate(syms) if i % toplam == parca]
    log(f"binance spot: {len(dirs)} dizin, bu parcada {len(syms)} sembol")

    def al(s):
        try:
            keys = s3_liste(f"data/spot/monthly/klines/{s}/4h/", dizin=False)
        except Exception as exc:
            return s, None, f"liste {exc!r}"
        keys = [k for k in keys if k.endswith(".zip") and "2017-07" <= k[-11:-4] <= "2020-12"]
        if not keys:
            return s, None, "donemde dosya yok"
        parts = []
        for k in keys:
            for dene in range(3):
                try:
                    r = requests.get(f"https://data.binance.vision/{k}", timeout=60)
                    if r.status_code != 200:
                        break
                    z = zipfile.ZipFile(io.BytesIO(r.content))
                    d = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[0, 1, 2, 3, 4, 5])
                    if not str(d.iloc[0, 0]).isdigit():
                        d = d.iloc[1:]
                    parts.append(d)
                    break
                except Exception:
                    time.sleep(2)
        if not parts:
            return s, None, "indirilemedi"
        d = pd.concat(parts).astype(float)
        d.columns = ["t", "o", "h", "l", "c", "v"]
        d["t"] = (d.t // 1000).astype("int64")
        d["symbol"] = s
        d["quote"] = "USDT" if s.endswith("USDT") else "BTC"
        return s, d, f"{len(d)} mum"

    out = []
    with ThreadPoolExecutor(12) as ex:
        for i, (s, d, msg) in enumerate(ex.map(al, syms)):
            if d is not None:
                out.append(d)
            if i % 50 == 0:
                log(f"{i}/{len(syms)} {s}: {msg}")
    df = pd.concat(out)[["symbol", "quote", "t", "o", "h", "l", "c", "v"]]
    df.to_csv(f"{OUT}/binance_{parca}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi binance_{parca}: {len(df)} satir, {df.symbol.nunique()} sembol")


def bitfinex():
    r = requests.get("https://api-pub.bitfinex.com/v2/conf/pub:list:pair:exchange", headers=H, timeout=60)
    ciftler = [p for p in r.json()[0] if p.endswith("USD") and ":" not in p]
    # eskiden islem goren ama listeden kalkmis olabilecek bilinen USD pariteleri
    ciftler = sorted(set(ciftler) | {"DSHUSD", "IOTUSD", "QTMUSD", "EDOUSD", "SANUSD", "ETPUSD", "OMGUSD", "BCHUSD", "RRTUSD"})
    log(f"bitfinex {len(ciftler)} parite")
    out = []
    bas0 = int(pd.Timestamp("2013-01-01", tz="UTC").timestamp() * 1000)
    bit0 = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
    for p in ciftler:
        rows, bas = [], bas0
        while bas < bit0:
            try:
                r = requests.get(f"https://api-pub.bitfinex.com/v2/candles/trade:4h:t{p}/hist",
                                 params={"start": bas, "end": bit0, "limit": 10000, "sort": 1}, headers=H, timeout=60)
                if r.status_code == 429:
                    time.sleep(30)
                    continue
                d = r.json()
            except Exception as exc:
                log(f"bitfinex {p} hata {exc!r}")
                break
            if not isinstance(d, list) or not d:
                break
            rows += d
            if len(d) < 10000:
                break
            bas = d[-1][0] + 1
            time.sleep(2)
        time.sleep(1.5)
        if rows:
            d = pd.DataFrame(rows, columns=["t", "o", "c", "h", "l", "v"])
            d["t"] = d.t // 1000
            d["symbol"], d["quote"] = p[:-3] + "USDT", "USD"
            out.append(d)
            log(f"bitfinex {p}: {len(d)} mum, {pd.to_datetime(d.t.min(), unit='s')} ->")
    df = pd.concat(out)[["symbol", "quote", "t", "o", "h", "l", "c", "v"]]
    df.to_csv(f"{OUT}/bitfinex.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi bitfinex: {len(df)} satir, {df.symbol.nunique()} sembol")


def poloniex():
    tum = []
    try:
        r = requests.get("https://poloniex.com/public", params={"command": "returnTicker"}, headers=H, timeout=60)
        log(f"poloniex eski ticker {r.status_code} {r.text[:150]}")
        ciftler = list(r.json().keys()) if r.ok else []
    except Exception as exc:
        log(f"poloniex eski api hata {exc!r}")
        ciftler = []
    if not ciftler:
        try:
            r = requests.get("https://api.poloniex.com/markets", headers=H, timeout=60)
            log(f"poloniex yeni markets {r.status_code}")
            ciftler = [m["symbol"] for m in r.json() if m["symbol"].endswith(("_USDT", "_BTC"))]
        except Exception as exc:
            log(f"poloniex yeni api hata {exc!r}")
            return
        # yeni API: tarih derinligi denemesi
        for p in ciftler:
            rows, bas = [], int(pd.Timestamp("2014-01-01", tz="UTC").timestamp() * 1000)
            bit = int(pd.Timestamp("2020-12-31", tz="UTC").timestamp() * 1000)
            while bas < bit:
                try:
                    rr = requests.get(f"https://api.poloniex.com/markets/{p}/candles",
                                      params={"interval": "HOUR_4", "startTime": bas, "endTime": min(bit, bas + 499 * 4 * 3600 * 1000),
                                              "limit": 500}, headers=H, timeout=60)
                    d = rr.json()
                except Exception as exc:
                    log(f"poloniex {p} hata {exc!r}")
                    break
                if isinstance(d, list) and d:
                    rows += d
                bas += 500 * 4 * 3600 * 1000
                time.sleep(0.25)
            if rows:
                # [low, high, open, close, amount, quantity, ..., startTime ...]
                d = pd.DataFrame([{"t": int(x[12]) // 1000, "l": float(x[0]), "h": float(x[1]), "o": float(x[2]),
                                   "c": float(x[3]), "v": float(x[5])} for x in rows])
                b, q = p.split("_")
                d["symbol"], d["quote"] = b + "USDT", q
                tum.append(d)
                log(f"poloniex {p}: {len(d)} mum, {pd.to_datetime(d.t.min(), unit='s')} ->")
    if tum:
        df = pd.concat(tum).drop_duplicates(["symbol", "quote", "t"])[["symbol", "quote", "t", "o", "h", "l", "c", "v"]]
        df.to_csv(f"{OUT}/poloniex.csv.gz", index=False, compression="gzip")
        log(f"kaydedildi poloniex: {len(df)} satir, {df.symbol.nunique()} sembol")


if __name__ == "__main__":
    mod = sys.argv[1]
    try:
        if mod == "binance":
            binance(int(sys.argv[2]), int(sys.argv[3]))
        elif mod == "bitfinex":
            bitfinex()
        elif mod == "poloniex":
            poloniex()
    except Exception as exc:
        log(f"HATA {mod}: {exc!r}")
    open(f"{OUT}/log_{'_'.join(sys.argv[1:])}.txt", "w").write("\n".join(LOG))
