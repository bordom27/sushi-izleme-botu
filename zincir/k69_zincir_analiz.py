"""K69 SHORT islemleri + zincir transfer ozellikleri: riskli coinde short acmasaydik ne olurdu?"""
import glob
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu
from sklearn.linear_model import LogisticRegression

W = pd.read_csv("zincir/k69_pencereler.csv", parse_dates=["t", "zaman"]); W["pid"] = W.index
F = pd.concat([pd.read_csv(f) for f in glob.glob("arastirma_cikti/zincir/k69/ozellik_*.csv")]).drop_duplicates("pid")
print("not:", F["not"].fillna("").str.split(":").str[0].value_counts().to_dict())
d = W.merge(F[F["not"].fillna("") == ""], on="pid")
# coin hem eth hem bsc'de ise daha cok transferi olan zinciri al
d = d.sort_values("n", ascending=False).drop_duplicates(["symbol", "zaman"]).sort_values("zaman").reset_index(drop=True)
d["dagitim_oran"] = (d.dagitim_n_s + 1) / (d.dagitim_n_b + 1)
d["cex_net_fark"] = d.cex_net_s - d.cex_net_b
OZ = ["hacim_oran", "tx_oran", "cex_gir_oran", "cex_gir_pay", "cex_net_fark", "yatirici_say_oran", "en_buyuk_yatir",
      "ilk5_yatir", "uyuyan_yatir", "uyuyan_en_buyuk", "dagitim_n_s", "dagitim_oran"]
L = lambda s: np.sign(s) * np.log1p(np.abs(s.fillna(0).clip(-1e4, 1e4)))
print(f"zincir verili islem: {len(d)} (canli filtre: {d.canli.sum()}) | isabet {d.kazandi.mean():.3f} R/i {d.R.mean():.3f}")


def auc(x, y):
    m = ~np.isnan(x); x, y = x[m], y[m]
    return mannwhitneyu(x[y == 1], x[y == 0]).statistic / ((y == 1).sum() * (y == 0).sum())


kay = (1 - d.kazandi).to_numpy()
print("\nKaybeden islemleri ayirt etme (AUC>0.5: ozellik yuksekse kayip):")
print(pd.Series({f: auc(d[f].to_numpy(float), kay) for f in OZ}).round(3).to_string())

# olay verisinden egitilmis risk modelleri (buyuk hareket, pump/squeeze)
T = pd.read_csv("zincir/transfer_pencereler.csv", parse_dates=["t"]); T["pid"] = T.index
G = pd.concat([pd.read_csv(f) for f in glob.glob("arastirma_cikti/zincir/transfer/ozellik_*.csv")]).drop_duplicates("pid")
e = T.merge(G[G["not"].fillna("") == ""], on="pid")
e["dagitim_oran"] = (e.dagitim_n_s + 1) / (e.dagitim_n_b + 1); e["cex_net_fark"] = e.cex_net_s - e.cex_net_b
for ad, poz in (("buyuk_hareket", ["dump", "pump"]), ("pump_riski", ["pump"])):
    x = e[e.tip.isin(poz + ["kontrol_" + p for p in poz])]
    m = LogisticRegression(max_iter=3000, C=0.3).fit(x[OZ].apply(L), x.tip.isin(poz))
    d[ad] = m.predict_proba(d[OZ].apply(L))[:, 1]
    print(f"\n{ad} skoru -> kayip AUC {auc(d[ad].to_numpy(), kay):.3f}")


def filtre_tablo(x, kol, ad):
    rows = []
    for q in (0.0, 0.5, 0.7, 0.8, 0.9, 0.95):
        esik = x[kol].quantile(q) if q else -np.inf
        k = x[x[kol] <= esik] if q else x
        if q:
            k = x[x[kol] < esik]
        at = x[x[kol] >= esik] if q else x.iloc[:0]
        rows.append({"eleme": f"ust %{round((1 - q) * 100)}" if q else "yok", "kalan": len(k), "isabet": k.kazandi.mean(),
                     "R_i": k.R.mean(), "topR": k.R.sum(), "elenen_isabet": at.kazandi.mean() if len(at) else np.nan})
    print(f"\n{ad}:"); print(pd.DataFrame(rows).round(3).to_string(index=False))


for kol in ("buyuk_hareket", "pump_riski", "hacim_oran", "cex_gir_oran"):
    filtre_tablo(d, kol, f"{kol} - tum islemler")
    filtre_tablo(d[d.canli], kol, f"{kol} - canli filtreli islemler")
# zaman: esigi 2025 sonuna kadar sec, 2026'da dene
tr = d.zaman < "2026-01-01"
for kol in ("buyuk_hareket", "pump_riski"):
    for q in (0.8, 0.9):
        es = d.loc[tr, kol].quantile(q)
        for ad, x in (("2026 tum", d[~tr]), ("2026 canli", d[~tr & d.canli])):
            k = x[x[kol] < es]; at = x[x[kol] >= es]
            print(f"zaman testi {kol} q{q} {ad}: once n={len(x)} isb {x.kazandi.mean():.3f} R {x.R.sum():.1f} -> sonra n={len(k)} isb {k.kazandi.mean():.3f} R {k.R.sum():.1f} | elenen n={len(at)} isb {at.kazandi.mean() if len(at) else float('nan'):.3f}")
