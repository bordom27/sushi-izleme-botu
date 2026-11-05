"""
BTC ek veri (2. tur, GitHub Actions): Bitfinex marjin long/short, dolar likiditesi (FRED), USD/JPY, jeopolitik risk,
Binance emir defteri derinligi. Cikti: arastirma_cikti/btc/*.csv.gz
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

OUT = "arastirma_cikti/btc"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def kaydet(df, ad):
    df.to_csv(f"{OUT}/{ad}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi {ad}: {len(df)} satir, {df.iloc[0, 0] if len(df) else '-'} -> {df.iloc[-1, 0] if len(df) else '-'}")


def bitfinex():
    out = None
    for yon in ("long", "short"):
        rows = []
        son = int(pd.Timestamp.utcnow().timestamp() * 1000)
        bas0 = int(pd.Timestamp("2018-01-01", tz="UTC").timestamp() * 1000)
        while son > bas0:
            r = requests.get(f"https://api-pub.bitfinex.com/v2/stats1/pos.size:1h:tBTCUSD:{yon}/hist",
                             params={"limit": 10000, "end": son, "sort": -1}, headers=H, timeout=60)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            d = r.json()
            if not d:
                break
            rows.extend(d)
            son = d[-1][0] - 1
            time.sleep(3)
        df = pd.DataFrame(rows, columns=["t", f"bfx_{yon}"]).drop_duplicates("t")
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        out = df if out is None else out.merge(df, on="t", how="outer")
        log(f"bitfinex {yon}: {len(df)}")
    kaydet(out.sort_values("t"), "bitfinex_marjin")


def fred_likidite():
    out = None
    for sid in ("WALCL", "RRPONTSYD", "WTREGEN", "M2SL", "DEXJPUS", "BAMLH0A0HYM2", "T5YIE"):
        for i in range(3):
            try:
                r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers=H, timeout=120)
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text))
                df.columns = ["t", sid]
                df["t"] = pd.to_datetime(df["t"])
                df[sid] = pd.to_numeric(df[sid], errors="coerce")
                out = df if out is None else out.merge(df, on="t", how="outer")
                log(f"fred {sid} {len(df)}")
                break
            except Exception as exc:
                log(f"fred {sid} deneme {i}: {exc!r}")
                time.sleep(10)
    if out is not None:
        kaydet(out.sort_values("t"), "likidite")


def yahoo():
    out = None
    for sym, ad in (("JPY=X", "usdjpy"), ("^TNX", "us10y"), ("^N225", "nikkei"), ("^IXIC", "nasdaq_y"), ("^VIX", "vix_y"), ("IBIT", "ibit")):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "1d", "range": "10y"},
                             headers=H, timeout=60)
            r.raise_for_status()
            j = r.json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            df = pd.DataFrame({"t": pd.to_datetime(j["timestamp"], unit="s").normalize(), ad: q["close"], f"{ad}_v": q.get("volume")})
            out = df if out is None else out.merge(df, on="t", how="outer")
            log(f"yahoo {sym} {len(df)}")
        except Exception as exc:
            log(f"HATA yahoo {sym}: {exc!r}")
        time.sleep(1)
    if out is not None:
        kaydet(out.sort_values("t"), "yahoo2")


def jeopolitik():
    for u in ("https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls",
              "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xlsx"):
        try:
            r = requests.get(u, headers=H, timeout=120)
            log(f"gpr {u} {r.status_code} {len(r.content)}")
            if not r.ok:
                continue
            df = pd.read_excel(io.BytesIO(r.content))
            tc = [c for c in df.columns if "date" in str(c).lower()][0]
            keep = [c for c in df.columns if str(c).upper() in ("GPRD", "GPRD_ACT", "GPRD_THREAT", "GPRD_MA7", "GPRD_MA30")]
            df = df[[tc] + keep].rename(columns={tc: "t"})
            df["t"] = pd.to_datetime(df["t"])
            kaydet(df[df.t >= "2017-01-01"], "jeopolitik")
            return
        except Exception as exc:
            log(f"HATA gpr {u}: {exc!r}")


def emir_defteri():
    gunler = [date(2023, 1, 1) + timedelta(days=i) for i in range((date.today() - date(2023, 1, 1)).days)]

    def al(g):
        u = f"https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-{g:%Y-%m-%d}.zip"
        try:
            r = requests.get(u, timeout=30)
            if r.status_code != 200:
                return None
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            df["t"] = pd.to_datetime(df["timestamp"])
            p = df.pivot_table(index=df.t.dt.floor("1h"), columns="percentage", values="notional", aggfunc="mean")
            return p
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(al, gunler) if p is not None]
    if not parts:
        log("emir defteri: dosya yok")
        return
    df = pd.concat(parts).sort_index()
    df.columns = [f"derinlik_{c}" for c in df.columns]
    kaydet(df.reset_index().rename(columns={"index": "t"}), "emir_defteri")


def wikipedia():
    rows = []
    for proje in ("en.wikipedia",):
        u = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{proje}/all-access/user/Bitcoin/daily/"
             f"20150701/{pd.Timestamp.utcnow():%Y%m%d}")
        r = requests.get(u, headers={"User-Agent": "k69-arastirma/1.0 (research)"}, timeout=60)
        r.raise_for_status()
        for it in r.json()["items"]:
            rows.append({"t": pd.to_datetime(it["timestamp"][:8]), "wiki_btc": it["views"]})
    kaydet(pd.DataFrame(rows), "wikipedia")


def mstr_8k():
    """SEC EDGAR: MicroStrategy (CIK 1050446) 8-K bildirim tarihleri (BTC alim duyurulari cogunlukla 8-K ile)."""
    r = requests.get("https://data.sec.gov/submissions/CIK0001050446.json",
                     headers={"User-Agent": "k69 arastirma research@example.com"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    rows = []
    def ekle(f):
        for form, d, item in zip(f["form"], f["filingDate"], f.get("items", [""] * len(f["form"]))):
            if form == "8-K":
                rows.append({"t": pd.to_datetime(d), "items": item})
    ekle(j["filings"]["recent"])
    for dosya in j["filings"].get("files", []):
        try:
            rr = requests.get(f"https://data.sec.gov/submissions/{dosya['name']}",
                              headers={"User-Agent": "k69 arastirma research@example.com"}, timeout=60)
            ekle(rr.json())
        except Exception as exc:
            log(f"mstr ek dosya {exc!r}")
    df = pd.DataFrame(rows)
    kaydet(df[df.t >= "2020-08-01"].sort_values("t"), "mstr_8k")


if __name__ == "__main__":
    import sys
    sadece = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    for ad, f in (("bitfinex", bitfinex), ("likidite", fred_likidite), ("yahoo", yahoo), ("jeopolitik", jeopolitik),
                  ("emir_defteri", emir_defteri), ("wikipedia", wikipedia), ("mstr_8k", mstr_8k)):
        if sadece and ad not in sadece:
            continue
        try:
            f()
        except Exception as exc:
            log(f"HATA {ad}: {exc!r}")
    import sys as _s; open(f"{OUT}/log_ek2{'_'+_s.argv[1] if len(_s.argv)>1 else ''}.txt", "w").write("\n".join(LOG))
