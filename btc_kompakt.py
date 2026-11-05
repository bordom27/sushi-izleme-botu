"""Tur 3b: sadece egitim+dogrulamada tutarli en guclu ozelliklerle kucuk model (asiri ogrenmeyi azaltmak icin).
Kullanim: python btc_kompakt.py [kilit]"""
import sys, json
import numpy as np, pandas as pd
import btc_lab as L, btc_analiz as A
from sklearn.ensemble import HistGradientBoostingClassifier
T = pd.read_csv("arastirma_cikti/btc_tekil.csv")
T = T[T.tutarli & ~T.ozellik.str.startswith(("PLASEBO", "liq_"))]   # likidasyon verisi 2024-10da bitiyor, canlida yok
kol = list(T.groupby("ozellik").guc.max().sort_values(ascending=False).head(25).index)
F = pd.read_pickle(A.TP).replace([np.inf, -np.inf], np.nan)[kol]
Y = pd.read_pickle(A.YP)
kilit = len(sys.argv) > 1 and sys.argv[1] == "kilit"
print("ozellikler:", ", ".join(kol))
P = {}
for k in A.KURULUM:
    y = Y[k]; p = pd.Series(np.nan, index=F.index)
    for yil in [2022, 2023, 2024, 2025, 2026]:
        bas = pd.Timestamp(f"{yil}-01-01"); bit = pd.Timestamp(f"{yil+1}-01-01")
        if not kilit: bit = min(bit, L.KILIT)
        eg = (F.index < bas - pd.Timedelta("4D")) & y.notna()
        te = (F.index >= bas) & (F.index < bit)
        if te.sum() == 0: continue
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=200, min_samples_leaf=500,
                                           l2_regularization=2.0, random_state=0)
        c = [x for x in kol if F.loc[eg, x].notna().sum() >= 500 and F.loc[eg, x].nunique() > 1]
        m.fit(F.loc[eg, c], (y[eg] > 0).astype(int)); p[te] = m.predict_proba(F.loc[te, c])[:, 1]
    P[k] = p
P = pd.DataFrame(P)
if not kilit:
    A.degerlendir(P)
    import shutil; shutil.copy("arastirma_cikti/btc_esik.json", "arastirma_cikti/btc_esik_kompakt.json")
else:
    esik = json.load(open("arastirma_cikti/btc_esik_kompakt.json"))
    Yk = Y.reindex(P.index); kk = P.index >= L.KILIT
    for k, e in esik.items():
        print(A.rapor(A.islemler(P[k][kk], Yk[k][kk], e, A.KURULUM[k][3]), f"KILITLI {k} esik {e}"))
        print("   " + A.rapor(A.islemler(pd.Series(1.0, index=P.index[kk]), Yk[k][kk], 0.5, A.KURULUM[k][3]), "filtresiz"))
