"""Duyuru sonrasi islem kurallari + ayni coinin rastgele zamanlariyla karsilastirma (taban)."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from duyuru import olay as OL

D, FR = OL.yukle()
M = pd.read_pickle("/tmp/claude-0/-home-claude/13e3c372-aa7b-58c8-a204-e85020633022/scratchpad/duyuru_olcum.pkl")
rng = np.random.default_rng(3)
# taban: ayni coin, duyurudan 20-60 gun once rastgele saat
B = []
for _, e in M[M.tur != "vadeli_acilis"].iterrows():
    T = D[e.symbol].index
    for _ in range(3):
        t = e.giris_t - pd.Timedelta(hours=int(rng.integers(20 * 24, 60 * 24)))
        i = T.searchsorted(t)
        if 200 < i < len(T) - 1:
            B.append({"zaman": T[i], "giris_t": T[i], "symbol": e.symbol, "tur": "taban_" + e.tur})
B = pd.DataFrame(B)
pd.set_option("display.width", 250)
rows = []
KUR = {"izleme": -1, "spot_delist": -1, "vadeli_delist": -1, "hodler": -1, "spot_listeleme": -1, "vadeli_acilis": -1}
for tur, yon in KUR.items():
    ev = M[M.tur == tur]; tb = B[B.tur == "taban_" + tur]
    for gec in ((0, 4, 24) if tur == "vadeli_acilis" else (0, 4)):
        for tut in (24, 72, 168):
            for stop in (0.10, 0.20, 0.35):
                a = OL.islem(D, FR, ev, yon, tut, stop, gec)
                b = OL.islem(D, FR, tb, yon, tut, stop, gec) if len(tb) else pd.DataFrame({"R": []})
                if len(a) < 10:
                    continue
                a["yil"] = pd.to_datetime(a.zaman).dt.year
                yil = a.groupby("yil").R.mean()
                rows.append({"tur": tur, "gecikme": gec, "tut_s": tut, "stop": stop, "n": len(a), "isabet": (a.R > 0).mean(),
                             "ort": a.R.mean(), "medyan": a.R.median(), "taban_isb": (b.R > 0).mean() if len(b) else np.nan,
                             "taban_ort": b.R.mean() if len(b) else np.nan,
                             "2024": yil.get(2024, np.nan), "2025": yil.get(2025, np.nan), "2026": yil.get(2026, np.nan)})
R = pd.DataFrame(rows)
R.to_csv("arastirma_cikti/duyuru/strateji.csv", index=False)
for tur in KUR:
    x = R[R.tur == tur].sort_values("ort", ascending=False)
    print(f"\n=== SHORT {tur}"); print(x.head(8).round(3).to_string(index=False))
