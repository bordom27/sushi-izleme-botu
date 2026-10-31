"""Hizli giris: duyurudan 1/2/5/15/60 dk sonra short; cikis 1 saatlik veriyle (stop + tutma), maliyet %0.2 + funding."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from duyuru import olay as OL

D, FR = OL.yukle()
O = pd.read_csv("duyuru/dakika_olaylar.csv", parse_dates=["zaman"])
K = pd.read_csv("arastirma_cikti/duyuru/dakika.csv.gz"); K["t"] = pd.to_datetime(K.t, unit="ms")


def sim(e, gec_dk, tut_s, stop):
    k = K[K.olay == e.name].set_index("t").sort_index()
    a = e.zaman
    gir_t = a.floor("min") + pd.Timedelta(minutes=gec_dk)
    if gir_t not in k.index:
        return None
    p = k.loc[gir_t, "o"]; st = p * (1 + stop)
    # dakikalik kisim (gir_t .. ilk tam saat), sonra 1 saatlik
    km = k[(k.index >= gir_t)]
    h1 = (gir_t.floor("h") + pd.Timedelta(hours=1))
    for t, r in km[km.index < h1].iterrows():
        if r.h >= st:
            return -(st / p - 1) - OL.MALIYET
    g = D[e.symbol]; T = g.index
    i = T.searchsorted(h1.as_unit("s")); bit = gir_t + pd.Timedelta(hours=tut_s)
    j = i; cik = None
    while j < len(T) and T[j] < bit:
        if g.h.iloc[j] >= st:
            cik = st; break
        j += 1
    if cik is None:
        j = min(j, len(T) - 1); cik = g.c.iloc[max(i, j - 1)]
    fr = FR.get(e.symbol)
    fz = fr[(fr.index > gir_t) & (fr.index <= bit)].sum() if fr is not None else 0
    return -(cik / p - 1) - OL.MALIYET + fz


rows = []
for tur in ("spot_delist", "izleme", "hodler", "spot_listeleme", "vadeli_delist"):
    ev = O[O.tur == tur]
    for gec in (1, 2, 5, 15, 60):
        for tut, stop in ((24, 0.10), (24, 0.20), (72, 0.20), (72, 0.35), (168, 0.20), (168, 0.35)):
            R = pd.Series([sim(e, gec, tut, stop) for _, e in ev.iterrows()]).dropna()
            yil = pd.Series([e.zaman.year for _, e in ev.iterrows()][:len(R)])
            rows.append({"tur": tur, "gecikme_dk": gec, "tut_s": tut, "stop": stop, "n": len(R), "isabet": (R > 0).mean(),
                         "ort": R.mean(), "medyan": R.median(), "en_kotu": R.min()})
X = pd.DataFrame(rows)
X.to_csv("arastirma_cikti/duyuru/hizli_giris.csv", index=False)
pd.set_option("display.width", 220)
for tur in X.tur.unique():
    print(f"\n=== {tur}"); print(X[X.tur == tur].pivot_table(index=["tut_s", "stop"], columns="gecikme_dk", values=["isabet", "ort"]).round(3).to_string())
