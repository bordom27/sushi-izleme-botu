"""
Borsa verisi (GitHub Actions'ta), K69 SHORT'un hisselerde testi icin.
  liste                    : BIST hisse listesi (KAP / Is Yatirim / Wikipedia) + ABD (S&P 500 + Nasdaq-100, Wikipedia)
  gunluk <parca> <toplam>  : Yahoo gunluk mumlar 2000-01-01 -> bugun
  saatlik <parca> <toplam> : Yahoo 1 saatlik mumlar (son ~730 gun), yerelde 4s'e cevrilir
Cikti: arastirma_cikti/borsa/liste.csv, gun_<parca>.csv.gz, saat_<parca>.csv.gz (symbol, piyasa, t[saniye], o, h, l, c, v)
Not: Yahoo sadece bugun islem goren hisseleri verir (borsadan cikanlar yok -> hayatta kalma yanliligi).
"""
from __future__ import annotations

import io
import os
import re
import sys
import time

import pandas as pd
import requests

OUT = "arastirma_cikti/borsa"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def bist_liste():
    kod = set()
    # 1) Is Yatirim hisse listesi sayfasi
    try:
        r = requests.get("https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Temel-Degerler-Ve-Oranlar.aspx", headers=H, timeout=60)
        k = set(re.findall(r"hisse=([A-Z0-9]{3,6})", r.text))
        log(f"isyatirim {r.status_code} {len(k)}")
        kod |= k
    except Exception as exc:
        log(f"isyatirim hata {exc!r}")
    # 2) KAP sirket listesi
    try:
        r = requests.get("https://www.kap.org.tr/tr/bist-sirketler", headers=H, timeout=60)
        k = set(re.findall(r"\b([A-Z][A-Z0-9]{3,5})\b(?=[^<]{0,40}</a>)", r.text))
        log(f"kap {r.status_code} {len(k)}")
        if r.ok and len(k) > 100:
            kod |= k
    except Exception as exc:
        log(f"kap hata {exc!r}")
    # 3) Wikipedia
    try:
        r = requests.get("https://en.wikipedia.org/wiki/List_of_companies_listed_on_Borsa_Istanbul", headers=H, timeout=60)
        for t in pd.read_html(io.StringIO(r.text)):
            for c in t.columns:
                if any(x in str(c).lower() for x in ("code", "ticker", "symbol")):
                    kod |= {str(v).strip().upper() for v in t[c] if re.fullmatch(r"[A-Za-z0-9]{3,6}", str(v).strip())}
        log(f"wikipedia bist toplam {len(kod)}")
    except Exception as exc:
        log(f"wikipedia bist hata {exc!r}")
    return sorted(kod)


def abd_liste():
    kod = set()
    for u, kol in (("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
                   ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker")):
        try:
            r = requests.get(u, headers=H, timeout=60)
            for t in pd.read_html(io.StringIO(r.text)):
                if kol in t.columns:
                    kod |= {str(v).replace(".", "-") for v in t[kol]}
            log(f"{u.split('/')[-1]} -> {len(kod)}")
        except Exception as exc:
            log(f"abd liste hata {u} {exc!r}")
    return sorted(kod)


def liste():
    b = bist_liste()
    a = abd_liste()
    df = pd.DataFrame({"symbol": [x + ".IS" for x in b] + a + ["XU100.IS", "^GSPC", "^NDX"],
                       "piyasa": ["BIST"] * len(b) + ["ABD"] * len(a) + ["BIST", "ABD", "ABD"]})
    df.to_csv(f"{OUT}/liste.csv", index=False)
    log(f"liste: BIST {len(b)}, ABD {len(a)}")


def yahoo(sym, interval, p1, p2):
    for dene in range(4):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": interval, "period1": p1, "period2": p2, "includePrePost": "false"},
                             headers=H, timeout=60)
            if r.status_code == 429:
                time.sleep(20 * (dene + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            j = r.json()["chart"]["result"][0]
            if "timestamp" not in j:
                return None
            q = j["indicators"]["quote"][0]
            d = pd.DataFrame({"t": j["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "v": q["volume"]})
            # bolunme/temettu duzeltmesi: adjclose orani ile OHLC olcekle (gunlukte var)
            adj = j["indicators"].get("adjclose")
            if adj:
                k = pd.Series(adj[0]["adjclose"]) / d.c
                for c in "ohlc":
                    d[c] = d[c] * k
            return d.dropna(subset=["c"])
        except Exception as exc:
            if dene == 3:
                log(f"{sym} {interval} hata {exc!r}")
            time.sleep(3)
    return None


def indir(parca, toplam, interval, ad):
    L = pd.read_csv(f"{OUT}/liste.csv")
    L = L.iloc[parca::toplam]
    simdi = int(time.time())
    p1 = 946684800 if interval == "1d" else simdi - 729 * 86400
    out = []
    for i, (s, p) in enumerate(zip(L.symbol, L.piyasa)):
        d = yahoo(s, interval, p1, simdi)
        if d is not None and len(d):
            d["symbol"], d["piyasa"] = s, p
            out.append(d)
        if i % 50 == 0:
            log(f"{ad} {i}/{len(L)} {s}: {0 if d is None else len(d)}")
        time.sleep(0.4)
    df = pd.concat(out)[["symbol", "piyasa", "t", "o", "h", "l", "c", "v"]]
    df.to_csv(f"{OUT}/{ad}_{parca}.csv.gz", index=False, compression="gzip")
    log(f"kaydedildi {ad}_{parca}: {len(df)} satir, {df.symbol.nunique()} sembol, "
        f"{pd.to_datetime(df.t.min(), unit='s')} -> {pd.to_datetime(df.t.max(), unit='s')}")


if __name__ == "__main__":
    mod = sys.argv[1]
    try:
        if mod == "liste":
            liste()
        elif mod == "kur":
            d = yahoo("TRY=X", "1d", 946684800, int(time.time()))
            d.to_csv(f"{OUT}/usdtry.csv.gz", index=False, compression="gzip")
            log(f"usdtry {len(d)} {pd.to_datetime(d.t.min(), unit='s')}")
        elif mod == "gunluk":
            if not os.path.exists(f"{OUT}/liste.csv"):
                liste()
            indir(int(sys.argv[2]), int(sys.argv[3]), "1d", "gun")
        elif mod == "saatlik":
            if not os.path.exists(f"{OUT}/liste.csv"):
                liste()
            indir(int(sys.argv[2]), int(sys.argv[3]), "1h", "saat")
    except Exception as exc:
        log(f"HATA {mod}: {exc!r}")
    open(f"{OUT}/log_{'_'.join(sys.argv[1:])}.txt", "w").write("\n".join(LOG))
