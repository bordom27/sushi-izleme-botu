"""
Zor bulunan BTC verileri (GitHub Actions'ta): ETF akislari (Farside), zincir ustu borsa akislari (Coin Metrics community),
likidasyon (Binance COIN-M arsivi), FOMC ve CPI tarihleri, Google Trends. Her biri bagimsiz; sonuc log'a yazilir.
"""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

OUT = "arastirma_cikti/btc"
os.makedirs(OUT, exist_ok=True)
TAR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "text/html,application/json,*/*", "Accept-Language": "en-US,en;q=0.9"}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def kaydet(df, ad):
    df.to_csv(f"{OUT}/{ad}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi {ad}: {len(df)} satir, {df.iloc[0, 0] if len(df) else '-'} -> {df.iloc[-1, 0] if len(df) else '-'}")


def etf():
    for u in ("https://farside.co.uk/bitcoin-etf-flow-all-data/", "https://farside.co.uk/btc/"):
        try:
            r = requests.get(u, headers=TAR, timeout=60)
            log(f"farside {u} -> {r.status_code} {len(r.text)}")
            if not r.ok:
                continue
            tabs = pd.read_html(io.StringIO(r.text))
            tab = max(tabs, key=len)
            tab.columns = [str(c[-1] if isinstance(c, tuple) else c) for c in tab.columns]
            tab = tab.rename(columns={tab.columns[0]: "t"})
            tab["t"] = pd.to_datetime(tab["t"], errors="coerce", dayfirst=True)
            tab = tab.dropna(subset=["t"])
            for c in tab.columns[1:]:
                tab[c] = pd.to_numeric(tab[c].astype(str).str.replace(",", "").str.replace("(", "-").str.replace(")", "")
                                       .str.replace("-$", "", regex=True), errors="coerce")
            kaydet(tab.sort_values("t"), "etf_akis")
            return
        except Exception as exc:
            log(f"HATA farside {u}: {exc!r}")


def coinmetrics():
    base = "https://community-api.coinmetrics.io/v4"
    try:
        cat = requests.get(f"{base}/catalog-all/asset-metrics", params={"assets": "btc"}, headers=TAR, timeout=60)
        if not cat.ok:
            cat = requests.get(f"{base}/catalog/asset-metrics", params={"assets": "btc"}, headers=TAR, timeout=60)
        log(f"coinmetrics katalog {cat.status_code}")
        mets = []
        for d in cat.json().get("data", []):
            for m in d.get("metrics", []):
                if any(f["frequency"] == "1d" for f in m.get("frequencies", [])):
                    mets.append(m["metric"])
        log(f"coinmetrics gunluk metrik sayisi {len(mets)}: {','.join(mets)[:3000]}")
    except Exception as exc:
        log(f"HATA coinmetrics katalog {exc!r}")
        mets = []
    istek = [m for m in mets if re.match(r"^(Flow|Sply|Adr|CapMVRV|CapRealUSD|NVT|SOPR|Tx|Fee|HashRate|Rev|SER|VelCur|IssTot|Vty)", m)]
    if not istek:
        istek = ["AdrActCnt", "CapMVRVCur", "CapRealUSD", "FlowInExUSD", "FlowOutExUSD", "SplyExNtv", "TxTfrValAdjUSD", "HashRate"]
    rows = []
    for i in range(0, len(istek), 10):
        grup = istek[i:i + 10]
        url, prm = f"{base}/timeseries/asset-metrics", {"assets": "btc", "metrics": ",".join(grup), "frequency": "1d",
                                                         "start_time": "2017-01-01", "page_size": 10000, "ignore_forbidden_errors": "true",
                                                         "ignore_unsupported_errors": "true"}
        while url:
            try:
                r = requests.get(url, params=prm, headers=TAR, timeout=60)
                if not r.ok:
                    log(f"coinmetrics {grup} -> {r.status_code} {r.text[:200]}")
                    break
                j = r.json()
                rows.extend(j.get("data", []))
                url, prm = j.get("next_page_url"), None
            except Exception as exc:
                log(f"HATA coinmetrics {grup}: {exc!r}")
                break
            time.sleep(0.7)
    if rows:
        df = pd.DataFrame(rows)
        df["t"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
        df = df.drop(columns=[c for c in ("time", "asset") if c in df]).groupby("t").first().reset_index()
        for c in df.columns[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        kaydet(df.sort_values("t"), "coinmetrics")


def likidasyon():
    """Binance COIN-M BTCUSD_PERP gunluk likidasyon kayitlari (USD-M arsivi kaldirildi)."""
    gunler = [date(2020, 9, 1) + timedelta(days=i) for i in range((date.today() - date(2020, 9, 1)).days)]

    def al(g):
        u = f"https://data.binance.vision/data/futures/cm/daily/liquidationSnapshot/BTCUSD_PERP/BTCUSD_PERP-liquidationSnapshot-{g:%Y-%m-%d}.zip"
        try:
            r = requests.get(u, timeout=30)
            if r.status_code != 200:
                return None
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            return df
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(al, gunler) if p is not None and len(p)]
    if not parts:
        log("likidasyon: dosya bulunamadi")
        return
    df = pd.concat(parts, ignore_index=True)
    log(f"likidasyon kolonlar {list(df.columns)}")
    tc = [c for c in df.columns if "time" in c.lower()][0]
    df["t"] = pd.to_datetime(df[tc], unit="ms")
    yon = [c for c in df.columns if c.lower() == "side"][0]
    miktar = [c for c in df.columns if "quantity" in c.lower() and "filled" not in c.lower()]
    q = miktar[0] if miktar else [c for c in df.columns if "qty" in c.lower()][0]
    df["usd"] = pd.to_numeric(df[q], errors="coerce") * 100          # COIN-M BTC kontrati 100 USD
    s = df.groupby([df.t.dt.floor("1h"), df[yon]]).usd.sum().unstack(fill_value=0).reset_index()
    s.columns = ["t"] + [f"liq_{c.lower()}" for c in s.columns[1:]]
    kaydet(s, "likidasyon_cm")


def fomc():
    tarih = []
    sayfalar = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"] + \
               [f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm" for y in (2017, 2018, 2019, 2020)]
    ay = "January|February|March|April|May|June|July|August|September|October|November|December"
    for u in sayfalar:
        try:
            r = requests.get(u, headers=TAR, timeout=60)
            log(f"fomc {u} {r.status_code}")
            if not r.ok:
                continue
            txt = re.sub(r"<[^>]+>", " ", r.text)
            if "fomccalendars" in u:
                for blok in re.split(r"(\d{4}) FOMC Meetings", txt)[1:]:
                    pass
                parcalar = re.split(r"(\d{4}) FOMC Meetings", txt)
                for i in range(1, len(parcalar), 2):
                    yil = int(parcalar[i])
                    for m in re.finditer(rf"({ay})(?:/(?:{ay}))?\s+(\d{{1,2}})(?:-(\d{{1,2}}))?\*?", parcalar[i + 1]):
                        gun = int(m.group(3) or m.group(2))
                        try:
                            tarih.append(pd.Timestamp(f"{yil}-{m.group(1)}-{gun}"))
                        except Exception:
                            pass
            else:
                yil = int(re.search(r"(\d{4})\.htm", u).group(1))
                for m in re.finditer(rf"({ay})\s+(\d{{1,2}})(?:-(\d{{1,2}}))?(?:,)?\s+{yil}\s+FOMC Meeting", txt):
                    gun = int(m.group(3) or m.group(2))
                    tarih.append(pd.Timestamp(f"{yil}-{m.group(1)}-{gun}"))
        except Exception as exc:
            log(f"HATA fomc {u}: {exc!r}")
    if tarih:
        kaydet(pd.DataFrame({"t": sorted(set(tarih))}), "fomc")


def cpi():
    try:
        r = requests.get("https://www.bls.gov/bls/news-release/cpi.htm", headers=TAR, timeout=60)
        log(f"bls cpi arsivi {r.status_code} {len(r.text)}")
        tarihler = re.findall(r"(\w+ \d{1,2}, \d{4})", re.sub(r"<[^>]+>", " ", r.text))
        t = pd.to_datetime(pd.Series(tarihler), errors="coerce").dropna()
        t = t[(t >= "2017-01-01")]
        if len(t):
            kaydet(pd.DataFrame({"t": sorted(set(t))}), "cpi_tarih")
    except Exception as exc:
        log(f"HATA cpi {exc!r}")


def trends():
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        parts = []
        bas = pd.Timestamp("2019-01-01")
        while bas < pd.Timestamp.utcnow().tz_localize(None):
            bit = bas + pd.Timedelta(days=260)
            pt.build_payload(["bitcoin"], timeframe=f"{bas:%Y-%m-%d} {bit:%Y-%m-%d}")
            d = pt.interest_over_time()
            if len(d):
                parts.append(d[["bitcoin"]].assign(parca=bas))
            bas = bit - pd.Timedelta(days=30)                      # cakisma: olcekleri birlestirmek icin
            time.sleep(8)
        df = pd.concat(parts).reset_index().rename(columns={"date": "t"})
        kaydet(df, "google_trends")
    except Exception as exc:
        log(f"HATA trends {exc!r}")


if __name__ == "__main__":
    for ad, f in (("etf", etf), ("coinmetrics", coinmetrics), ("likidasyon", likidasyon), ("fomc", fomc), ("cpi", cpi), ("trends", trends)):
        try:
            f()
        except Exception as exc:
            log(f"HATA {ad}: {exc!r}")
    open(f"{OUT}/log_ara.txt", "w").write("\n".join(LOG))
