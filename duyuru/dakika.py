"""Duyuru anindan itibaren 1 dakikalik vadeli mumlar (-10 dk .. +180 dk). Cikti: arastirma_cikti/duyuru/dakika.csv.gz"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import veri

O = pd.read_csv("duyuru/dakika_olaylar.csv", parse_dates=["zaman"])
rows = []
for i, e in O.iterrows():
    s = int((e.zaman - pd.Timedelta(minutes=10)).timestamp() * 1000)
    try:
        d = veri._get("/fapi/v1/klines", {"symbol": e.symbol, "interval": "1m", "startTime": s, "limit": 190}, veri.FAPI_URLS)
    except Exception as exc:
        print("yok", e.symbol, exc); d = []
    for k in d:
        rows.append({"olay": i, "symbol": e.symbol, "t": k[0], "o": k[1], "h": k[2], "l": k[3], "c": k[4], "v": k[5]})
    time.sleep(0.15)
    print(i, e.symbol, len(d), flush=True)
os.makedirs("arastirma_cikti/duyuru", exist_ok=True)
pd.DataFrame(rows).to_csv("arastirma_cikti/duyuru/dakika.csv.gz", index=False, compression="gzip")
