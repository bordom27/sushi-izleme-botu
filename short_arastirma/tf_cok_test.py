"""
K69 SHORT 2s / 8s / 12s (27 Eki 2026). 2s: 1s verisinden (2024+), 8s/12s: 4s verisinden (2020+) yeniden ornekleme.
Ayni kurallar, ayni mum sayilari; canli filtre (ayni mumda >=3 coin ya da ⭐⭐). 4s ile birlikte calistirma da olculur.
Kullanim: python short_arastirma/tf_cok_test.py
"""
from __future__ import annotations

import glob
import multiprocessing as mp
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tf_long_test as T                                                  # noqa: E402

TFS = {"4h": "4h", "8h": "4h", "12h": "4h", "2h": "1h"}     # hedef tf -> kaynak veri
AGG = {"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}


def _dosya(args):
    yol, kaynak = args
    K = pd.read_csv(yol)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    out = []
    for s, g in K.groupby("symbol", sort=True):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
        g = g[g.v > 0]
        for tf, kk in TFS.items():
            if kk != kaynak:
                continue
            x = g if tf == kaynak else g.resample(tf.replace("h", "h"), origin="epoch").agg(AGG).dropna()
            if len(x) < 300:
                continue
            out += T.islemler(s, x, tf, dict(tf=tf, yon=-1, A=T.TEMEL))
    return out


if __name__ == "__main__":
    F = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok/fund_*.csv.gz"))], ignore_index=True)
    F["t"] = pd.to_datetime(F["t"], unit="ms")
    T.FR = {s: g.set_index("t")["fr"].sort_index() for s, g in F.groupby("symbol")}
    isler = [(f, "4h") for f in sorted(glob.glob("arastirma_cikti/dok/k4h_*.csv.gz"))] + \
            [(f, "1h") for f in sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))]
    with mp.get_context("fork").Pool(2, maxtasksperchild=1) as hv:
        res = hv.map(_dosya, isler, chunksize=1)
    t = pd.DataFrame([r for lst in res for r in lst])
    t["kume"] = t.groupby(["var", "giris"]).symbol.transform("size")
    t.to_pickle(os.path.join(os.environ.get("SP", "/tmp"), "tf_cok.pkl"))
    a = t[t.alindi].copy()
    a["filtre"] = (a.kume >= 3) | (a.yildiz == 2)
    B24 = pd.Timestamp("2024-01-01")
    rows = []
    for tf in TFS:
        x = a[a["var"] == tf]
        rows.append(T.ozet(x, f"{tf} tum"))
        rows.append(T.ozet(x[x.filtre], f"{tf} canli filtre"))
        rows.append(T.ozet(x[x.filtre], f"{tf} canli filtre 2024+", B24))
    s4 = a[(a["var"] == "4h") & a.filtre]
    for tf in ("8h", "12h"):
        rows.append(T.ozet(T.birlesik(s4, a[(a["var"] == tf) & a.filtre]), f"4h + {tf} birlikte (filtre)"))
    rows.append(T.ozet(T.birlesik(T.birlesik(s4, a[(a["var"] == "8h") & a.filtre]), a[(a["var"] == "12h") & a.filtre]),
                       "4h + 8h + 12h birlikte (filtre)"))
    rows.append(T.ozet(T.birlesik(s4[s4.giris >= B24], a[(a["var"] == "2h") & a.filtre]), "4h + 2h birlikte (filtre, 2024+)"))
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 320, "display.max_columns", 30)
    print(df.to_string(index=False))
    df.to_csv("short_arastirma/kos_tf_cok.csv", index=False)
