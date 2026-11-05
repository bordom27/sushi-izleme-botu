"""
BTC analizi (yerel). Kullanim: python btc_analiz.py <adim>
  tablo    : ozellik tablosunu kur ve kaydet (arastirma_cikti/btc_ozellik.pkl)
  tekil    : her ozelligin tek basina etkisi (egitim <2024, dogrulama 2024-01..2025-06), long ve short
  model    : yila gore ileri yuruyen model (HistGradientBoosting) + esik secimi (dogrulama), sanal islemler
  kilit    : secilen sistemi kilitli donemde (2025-07 -> bugun) BIR KEZ olc
KILITLI DONEM hicbir secimde kullanilmaz.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import btc_lab as L

TP = "arastirma_cikti/btc_ozellik.pkl"
YP = "arastirma_cikti/btc_hedef.pkl"
# islem tanimlari: (yon, stop_atr, hedef_r, maks_mum) - 1 saatlik ATR ile
KURULUM = {
    "L_kisa": (1, 1.5, 1.0, 24), "S_kisa": (-1, 1.5, 1.0, 24),
    "L_orta": (1, 3.0, 1.0, 72), "S_orta": (-1, 3.0, 1.0, 72),
    "L_yuk": (1, 3.0, 0.5, 72), "S_yuk": (-1, 3.0, 0.5, 72),        # yuksek isabet (kucuk hedef)
}


def tablo():
    F = L.tablo()
    g = L.fiyat_1h()
    Y = pd.DataFrame({k: L.sonuc(g, *v) for k, v in KURULUM.items()})
    Y = Y.reindex(F.index)
    F.to_pickle(TP)
    Y.to_pickle(YP)
    print("ozellik", F.shape, "hedef", Y.shape, F.index.min(), F.index.max())
    dolu = F.notna().mean().sort_values()
    print("en az dolu 20 ozellik:\n", dolu.head(20).round(2).to_string())


def donem(ix):
    return np.where(ix < L.EGIT_BIT, "egit", np.where(ix < L.KILIT, "dogr", "KILIT"))


def tekil():
    F = pd.read_pickle(TP)
    Y = pd.read_pickle(YP)
    d = donem(F.index)
    m = d != "KILIT"
    F, Y, d = F[m], Y[m], d[m]
    rows = []
    for k in ("L_orta", "S_orta"):
        y = Y[k]
        for c in F.columns:
            x = F[c]
            ok = x.notna() & y.notna()
            if ok.sum() < 3000 or x[ok].nunique() < 3:
                continue
            try:
                q = pd.qcut(x[ok].rank(method="first"), 5, labels=False)
            except Exception:
                continue
            t = pd.DataFrame({"q": q, "y": y[ok], "d": d[ok.to_numpy()]})
            g = t.groupby(["d", "q"]).y.mean().unstack()
            if "egit" not in g.index or "dogr" not in g.index:
                continue
            e = g.loc["egit"]; v = g.loc["dogr"]
            fark_e = e.iloc[-1] - e.iloc[0]; fark_v = v.iloc[-1] - v.iloc[0]
            rows.append({"kurulum": k, "ozellik": c, "egit_ust_alt": round(fark_e, 3), "dogr_ust_alt": round(fark_v, 3),
                         "tutarli": np.sign(fark_e) == np.sign(fark_v), "guc": round(min(abs(fark_e), abs(fark_v)) * (np.sign(fark_e) == np.sign(fark_v)), 3),
                         "egit_q": " ".join(f"{z:+.2f}" for z in e.values), "dogr_q": " ".join(f"{z:+.2f}" for z in v.values)})
    R = pd.DataFrame(rows).sort_values("guc", ascending=False)
    R.to_csv("arastirma_cikti/btc_tekil.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    for k in ("L_orta", "S_orta"):
        print(f"\n=== {k}: egitim ve dogrulamada ayni yonde en guclu 30 ozellik (ust %20 - alt %20 islem basi R farki)")
        print(R[(R.kurulum == k)].head(30).to_string(index=False))


def model(kilit=False, egit_bas="2015-01-01"):
    from sklearn.ensemble import HistGradientBoostingClassifier
    F = pd.read_pickle(TP)
    Y = pd.read_pickle(YP)
    F = F.replace([np.inf, -np.inf], np.nan)
    sonuc = {}
    yillar = [2022, 2023, 2024, 2025, 2026]
    for k in KURULUM:
        y = Y[k]
        p = pd.Series(np.nan, index=F.index)
        for yil in yillar:
            bas = pd.Timestamp(f"{yil}-01-01"); bit = pd.Timestamp(f"{yil + 1}-01-01")
            if not kilit:
                bit = min(bit, L.KILIT)
            egit = (F.index < bas - pd.Timedelta("4D")) & (F.index >= pd.Timestamp(egit_bas)) & y.notna()   # 4 gun bosluk: hedef sizmasin
            test = (F.index >= bas) & (F.index < bit)
            if not kilit:
                test &= F.index < L.KILIT
            if egit.sum() < 5000 or test.sum() == 0:
                continue
            m = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.04, max_iter=300, min_samples_leaf=200,
                                               l2_regularization=1.0, random_state=0)
            m.fit(F[egit], (y[egit] > 0).astype(int))
            p[test] = m.predict_proba(F[test])[:, 1]
        sonuc[k] = p
        print(k, "tahmin dolu", p.notna().sum(), flush=True)
    P = pd.DataFrame(sonuc)
    P.to_pickle("arastirma_cikti/btc_tahmin" + ("_kilit" if kilit else "") + f"_{egit_bas[:4]}.pkl")
    return P


def islemler(p, y, esik, maks, karar_sikligi=1):
    """Ust uste binmeyen sanal islemler: olasilik >= esik olan ilk mumda gir, sure dolana kadar yeni islem yok."""
    ix = p.index
    out = []
    serbest = ix[0]
    for i, t in enumerate(ix):
        if karar_sikligi > 1 and t.hour % karar_sikligi:
            continue
        if t < serbest or not (p.iloc[i] >= esik) or np.isnan(y.iloc[i]):
            continue
        out.append((t, y.iloc[i]))
        serbest = t + pd.Timedelta(hours=maks)                               # temkinli: en uzun sure kadar bekle
    return pd.DataFrame(out, columns=["t", "R"])


def rapor(tr, ad):
    if len(tr) == 0:
        return f"{ad}: islem yok"
    yy = " ".join(f"{a}:{len(b)}/%{(b.R > 0).mean() * 100:.0f}/{b.R.sum():+.1f}" for a, b in tr.groupby(tr.t.dt.year))
    return f"{ad}: n={len(tr)} isabet=%{(tr.R > 0).mean() * 100:.1f} R/islem={tr.R.mean():+.3f} toplam={tr.R.sum():+.1f} | {yy}"


def degerlendir(P):
    Y = pd.read_pickle(YP).reindex(P.index)
    d = donem(P.index)
    satir = {}
    for k, (yon, sa, tr_, maks) in KURULUM.items():
        p, y = P[k], Y[k]
        # esik: 2022-2023 (modelin ilk ileri tahminleri) uzerinde secilir, 2024-2025H1 dogrulamada olculur
        sec = (P.index >= "2022-01-01") & (P.index < L.EGIT_BIT)
        dog = (d == "dogr")
        en_iyi = None
        for esik in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
            a = islemler(p[sec], y[sec], esik, maks)
            if len(a) < 40:
                continue
            skor = a.R.mean()
            if en_iyi is None or skor > en_iyi[1]:
                en_iyi = (esik, skor, len(a))
        if en_iyi is None:
            print(k, "yeterli islem yok"); continue
        esik = en_iyi[0]
        a = islemler(p[sec], y[sec], esik, maks)
        b = islemler(p[dog], y[dog], esik, maks)
        hepsi = islemler(pd.Series(1.0, index=P.index[dog]), y[dog], 0.5, maks)
        print(f"\n### {k} (yon {yon}, stop {sa} ATR, hedef {tr_}R, en fazla {maks} saat) secilen esik {esik}")
        print("  " + rapor(a, "2022-23 (esik secimi)"))
        print("  " + rapor(b, "2024-25H1 (dogrulama)"))
        print("  " + rapor(hepsi, "  karsilastirma: filtresiz her firsat (dogrulama)"))
        satir[k] = esik
    json.dump(satir, open("arastirma_cikti/btc_esik.json", "w"))


if __name__ == "__main__":
    a = sys.argv[1]
    if a == "tablo":
        tablo()
    elif a == "tekil":
        tekil()
    elif a == "model":
        eb = sys.argv[2] if len(sys.argv) > 2 else "2015-01-01"
        print("EGITIM BASLANGICI", eb)
        degerlendir(model(egit_bas=eb))
    elif a == "kilit":
        P = model(kilit=True)
        esik = json.load(open("arastirma_cikti/btc_esik.json"))
        Y = pd.read_pickle(YP).reindex(P.index)
        k_ = P.index >= L.KILIT
        for k, e in esik.items():
            print(rapor(islemler(P[k][k_], Y[k][k_], e, KURULUM[k][3]), f"KILITLI {k} esik {e}"))
