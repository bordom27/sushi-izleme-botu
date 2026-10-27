"""Transfer testi analizi (yerel): dump/pump oncesi 48s ozellikleri vs ayni coinin kontrol donemleri."""
import glob
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.metrics import roc_auc_score

W = pd.read_csv("zincir/transfer_pencereler.csv", parse_dates=["t"]); W["pid"] = W.index
F = pd.concat([pd.read_csv(f) for f in glob.glob("arastirma_cikti/zincir/transfer/ozellik_*.csv")]).drop_duplicates("pid")
print("not dagilimi:", F["not"].fillna("").str.split(":").str[0].value_counts().to_dict())
d = W.merge(F[F["not"].fillna("") == ""], on="pid")
d["dagitim_oran"] = (d.dagitim_n_s + 1) / (d.dagitim_n_b + 1)
d["cex_net_fark"] = d.cex_net_s - d.cex_net_b
OZ = ["hacim_oran", "tx_oran", "cex_gir_oran", "cex_gir_pay", "cex_net_s", "cex_net_fark", "yatirici_say_oran", "en_buyuk_yatir",
      "ilk5_yatir", "uyuyan_yatir", "uyuyan_en_buyuk", "dagitim_n_s", "dagitim_oran", "dagitim_m_s"]
FIY = ["r42", "vx18", "r6"]
pd.set_option("display.width", 220)


def auc(x, y):
    m = ~np.isnan(x); x, y = x[m], y[m]
    if (y == 1).sum() < 5 or (y == 0).sum() < 5:
        return np.nan
    return mannwhitneyu(x[y == 1], x[y == 0]).statistic / ((y == 1).sum() * (y == 0).sum())


L = lambda s: np.sign(s) * np.log1p(np.abs(s.fillna(0).clip(-1e4, 1e4)))
for olay in ("dump", "pump"):
    x = d[d.tip.isin([olay, "kontrol_" + olay])].copy()
    x["y"] = (x.tip == olay).astype(int)
    print(f"\n========== {olay.upper()}  olay={x.y.sum()} kontrol={(1 - x.y).sum()}  (eth {(x.zincir == 'eth').sum()}, bsc {(x.zincir == 'bsc').sum()})")
    tab = x.groupby("tip")[OZ].median().T
    tab["AUC"] = [auc(x[f].to_numpy(float), x.y.to_numpy()) for f in OZ]
    for z in ("eth", "bsc"):
        xz = x[x.zincir == z]
        tab["AUC_" + z] = [auc(xz[f].to_numpy(float), xz.y.to_numpy()) for f in OZ]
    print(tab.round(3).to_string())
    print("fiyat AUC:", {f: round(auc(x[f].to_numpy(float), x.y.to_numpy()), 3) for f in FIY})
    X0 = x[FIY].fillna(0)
    X1 = pd.concat([X0, x[OZ].apply(L)], axis=1)
    for ad, X in (("fiyat", X0), ("fiyat+transfer", X1), ("sadece transfer", x[OZ].apply(L))):
        p = cross_val_predict(LogisticRegression(max_iter=3000, C=0.3), X, x.y, cv=GroupKFold(5), groups=x.symbol, method="predict_proba")[:, 1]
        tr = x.t < "2026-03-01"
        m = LogisticRegression(max_iter=3000, C=0.3).fit(X[tr], x.y[tr])
        print(f"  {ad:16s} CV AUC {roc_auc_score(x.y, p):.3f} | zaman bolmesi (2026-03+) AUC {roc_auc_score(x.y[~tr], m.predict_proba(X[~tr])[:, 1]):.3f} n_test={(~tr).sum()}")
    # en uc dilim: olay payi
    for f in ("en_buyuk_yatir", "uyuyan_en_buyuk", "cex_gir_oran", "dagitim_n_s"):
        q = x[f].rank(pct=True)
        print(f"  {f}: ust %10 dilimde olay payi {x.y[q >= 0.9].mean():.2f} (n={(q >= 0.9).sum()}), ust %2: {x.y[q >= 0.98].mean():.2f}, taban {x.y.mean():.2f}")
