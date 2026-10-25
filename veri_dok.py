"""
Short arastirmasi icin ham veri dokumu (GitHub Actions'ta calisir).
Tum USDT-M surekli vadeli sozlesmeler (kapanmis/delist olanlar dahil, hayatta kalma yanliligini azaltmak icin):
  4 saatlik vadeli mumlar (2019-09'dan) + funding gecmisi.
Kullanim: python veri_dok.py <parca> <toplam_parca> [aralik]
  aralik verilirse (or. 1h): 2024-01'den o aralikta mumlar, cikti dok<aralik>/k<aralik>_<parca>.csv.gz (funding yok)
Cikti: arastirma_cikti/dok/meta.csv, dok/k4h_<parca>.csv.gz, dok/fund_<parca>.csv.gz
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

import veri

OUT = "arastirma_cikti/dok"
BAS = "2019-09-01"


def semboller():
    info = veri._get("/fapi/v1/exchangeInfo", {}, veri.FAPI_URLS)
    rows = []
    for s in info["symbols"]:
        if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT":
            continue
        rows.append({"symbol": s["symbol"], "status": s.get("status"), "onboard": s.get("onboardDate"),
                     "delivery": s.get("deliveryDate"), "base": s.get("baseAsset"), "underlying": s.get("underlyingType")})
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def funding(sym):
    rows, start = [], int(pd.Timestamp(BAS, tz="UTC").timestamp() * 1000)
    while True:
        d = veri._get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": start, "limit": 1000}, veri.FAPI_URLS)
        if not d:
            break
        rows.extend(d)
        if len(d) < 1000:
            break
        start = d[-1]["fundingTime"] + 1
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["symbol", "t", "fr"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({"symbol": sym, "t": df["fundingTime"].astype("int64"), "fr": df["fundingRate"].astype(float)})


def main():
    global OUT, BAS
    parca, toplam = int(sys.argv[1]), int(sys.argv[2])
    aralik = sys.argv[3] if len(sys.argv) > 3 else "4h"
    if aralik != "4h":
        OUT, BAS = f"arastirma_cikti/dok{aralik}", "2024-01-01"
    os.makedirs(OUT, exist_ok=True)
    meta = semboller()
    if parca == 0:
        meta.to_csv(f"{OUT}/meta.csv", index=False)
    print("toplam sozlesme", len(meta), flush=True)
    benim = meta.symbol.tolist()[parca::toplam]
    K, F = [], []
    for i, s in enumerate(benim):
        try:
            df = veri.mumlar("F:" + s, aralik, BAS)
            if len(df):
                K.append(pd.DataFrame({"symbol": s, "t": (df.open_time.astype("int64") // 10**6),
                                       "o": df.open, "h": df.high, "l": df.low, "c": df.close, "v": df.volume}))
        except Exception as exc:
            print("mum yok", s, exc, flush=True)
        if aralik != "4h":
            print(i + 1, len(benim), s, len(K[-1]) if K else 0, flush=True)
            continue
        try:
            F.append(funding(s))
        except Exception as exc:
            print("funding yok", s, exc, flush=True)
        print(i + 1, len(benim), s, len(K[-1]) if K else 0, flush=True)
    pd.concat(K).to_csv(f"{OUT}/k{aralik}_{parca}.csv.gz", index=False, compression="gzip", float_format="%.7g")
    if aralik != "4h":
        return
    pd.concat(F).to_csv(f"{OUT}/fund_{parca}.csv.gz", index=False, compression="gzip", float_format="%.6g")


if __name__ == "__main__":
    main()
