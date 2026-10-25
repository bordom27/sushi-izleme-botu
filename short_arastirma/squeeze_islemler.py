"""
K69 SHORT squeeze filtresi arastirmasi - adim 1: canli kurallarla (short_retest.sinyaller) tum gecmis islemler +
sinyal anindaki pump/squeeze risk ozellikleri (sadece gecmis veri).
Kullanim: python short_arastirma/squeeze_islemler.py <cikti.pkl>
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import multiprocessing as mp
import numpy as np, pandas as pd
import short_lab as S, short_retest as K

MALIYET = 0.002
HEDEF_A = {"hedef_r": float(os.environ["HEDEF"]), "hedef_r_sig": float(os.environ["HEDEF"])} if os.environ.get("HEDEF") else None
D, FR, M = S.yukle()

# piyasa geneli: her 4s mumda coinlerin 24s getirisi
_C = pd.DataFrame({s: g.c for s, g in D.items()})
_R6 = _C / _C.shift(6) - 1
PIYASA = pd.DataFrame({"genislik": (_R6 > 0).sum(1) / _R6.notna().sum(1).clip(lower=1),
                       "pompa_orani": (_R6 > 0.10).sum(1) / _R6.notna().sum(1).clip(lower=1),
                       "btc_r6": _R6["BTCUSDT"]})


def bir(s):
    g = D[s]
    sig = K.sinyaller(g, A=HEDEF_A)
    if not sig:
        return []
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    x = K.gostergeler(g)
    atr, va = x["atr"], x["va"]
    T = g.index; n = len(c)
    pc = np.r_[np.nan, c[:-1]]
    yukari = (h - pc) / pc                                   # mum ici en buyuk yukari sicrama
    atr_ort = pd.Series(atr).rolling(100).mean().to_numpy()
    v_med = pd.Series(v).rolling(180, min_periods=60).median().to_numpy()
    fr = FR.get(s)
    rows = []
    serbest = -1
    for z in sig:
        i = z["ix"]
        if i >= n - 1:
            continue
        e, st, tg = z["giris"], z["stop"], z["hedef"]
        risk = (st - e) / e
        # sonuc
        neden, cik, j = "ZAMAN", c[min(n - 1, i + 30)], min(n - 1, i + 30)
        for jj in range(i + 1, min(n, i + 31)):
            if h[jj] >= st:
                neden, cik, j = "STOP", st, jj; break
            if l[jj] <= tg:
                neden, cik, j = "HEDEF", tg, jj; break
        kapandi = (j < n - 1) or neden != "ZAMAN"
        t_cik = T[j] + pd.Timedelta(hours=4)
        t_sig = T[i] + pd.Timedelta(hours=4)                 # sinyal mumunun kapanisi
        fz = 0.0; f1 = f3 = f9 = fz_ort = np.nan
        if fr is not None and len(fr):
            fz = fr[(fr.index > t_sig) & (fr.index <= t_cik)].sum()
            gec = fr[fr.index <= t_sig]
            if len(gec):
                f1 = gec.iloc[-1]; f3 = gec.iloc[-3:].sum(); f9 = gec.iloc[-9:].sum()
                fz_ort = gec.iloc[-90:].mean()
        Rr = ((e - cik) / e - MALIYET + fz) / risk
        mfe_yuk = (h[i + 1:j + 1].max() - e) / (st - e) if j > i else np.nan
        a30 = slice(max(0, i - 179), i + 1)
        p = PIYASA.loc[T[i]] if T[i] in PIYASA.index else None
        rows.append({
            "symbol": s, "zaman": T[i], "neden": neden, "R": Rr, "kazandi": int(Rr > 0), "kapandi": kapandi,
            "sure": j - i, "risk": risk, "yildiz": z["yildiz"], "qv": z["gunluk_hacim"], "hedef_r": z["hedef_r"],
            "dokunus": z["dokunus"], "kir_boy": z["kirilim_boy"], "vor3": z["hacim_orani"], "kir_v": z["kirilim_hacim"],
            # funding (short pozisyon pozitif funding alir; negatif = short kalabalik -> squeeze riski)
            "f1": f1, "f3": f3, "f9": f9, "f90": fz_ort,
            # fiyat / volatilite
            "r6": c[i] / c[i - 6] - 1, "r42": c[i] / c[i - 42] - 1 if i >= 42 else np.nan,
            "r180": c[i] / c[i - 180] - 1 if i >= 180 else np.nan,
            "atrp": atr[i] / c[i], "sikisma": atr[i] / atr_ort[i] if atr_ort[i] > 0 else np.nan,
            "pompa30": int((yukari[a30] > 0.10).sum()), "maks_sicrama30": np.nanmax(yukari[a30]),
            "pompa30_atr": int(((h[a30] - pc[a30]) > 3 * atr[a30]).sum()),
            "hacim_tepe6": np.nanmax(v[i - 5:i + 1] / v_med[i]) if v_med[i] > 0 else np.nan,
            "sig_hacim": v[i] / v_med[i] if v_med[i] > 0 else np.nan,
            "yas": i, "derin": (z["seviye"] - l[z["ix"] - 1 if False else i]) / atr[i],
            "genislik": p["genislik"] if p is not None else np.nan,
            "pompa_orani": p["pompa_orani"] if p is not None else np.nan,
            "btc_r6": p["btc_r6"] if p is not None else np.nan,
            "mfe_yuk": mfe_yuk,
        })
    return rows


if __name__ == "__main__":
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(bir, list(D), chunksize=8)
    t = pd.DataFrame([r for l in out for r in l]).sort_values("zaman").reset_index(drop=True)
    t.to_pickle(sys.argv[1])
    print(len(t), "islem; isabet", round(t.kazandi.mean() * 100, 1), "ortR", round(t.R.mean(), 3))
