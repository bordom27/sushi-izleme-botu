"""
Sinyal dogrulugu arastirmasi (v6.2): goreli guc, piyasa genisligi, sikisma + meta-etiketleme.
Cikti: arastirma_cikti/dogruluk.txt, dogruluk_islemler.csv
"""
from __future__ import annotations

import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import arastirma as A
import kirilim_v6 as k
import veri
from coin_listesi import COINLER

OUT = "arastirma_cikti"
B = {"basarisiz_cikis": True, "bc_bar": 3, "bc_atr": 0.3}


def coin_ozellik(df):
    c = df["close"].to_numpy(float); h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    o = df["open"].to_numpy(float); v = df["volume"].to_numpy(float)
    atr14 = k.rma(k.true_range(h, l, c, True), 14)
    atr100 = k.rma(k.true_range(h, l, c, True), 100)
    sma20 = pd.Series(c).rolling(20).mean().to_numpy(); sd20 = pd.Series(c).rolling(20).std().to_numpy()
    bbw = 4 * sd20 / sma20
    bbw_pct = pd.Series(bbw).rolling(120).rank(pct=True).to_numpy()
    e21 = k.ema(c, 21); e50 = k.ema(c, 50)
    rsi = k.rsi(c, 14)
    dp, dm, adx = k.dmi(h, l, c, 14, 14)
    f = pd.DataFrame({
        "c": c, "o": o, "h": h, "l": l, "v": v, "atr": atr14, "sq": atr14 / atr100,
        "bbw_pct": bbw_pct, "e21": e21, "ust50": (c > e50).astype(float), "rsi": rsi, "adx": adx,
        "ret42": pd.Series(c).pct_change(42).to_numpy(), "ret180": pd.Series(c).pct_change(180).to_numpy(),
        "hh80": pd.Series(h).rolling(80).max().shift(1).to_numpy(), "ll80": pd.Series(l).rolling(80).min().shift(1).to_numpy(),
        "vort": pd.Series(v).rolling(20).mean().shift(1).to_numpy(),
    }, index=pd.to_datetime(df["open_time"]))
    return f


def tercil(tr, kol):
    t = tr.dropna(subset=[kol])
    IS = t[t.donem == "IS"]
    if len(IS) < 40:
        return None
    q1, q2 = IS[kol].quantile([1 / 3, 2 / 3])
    t = t.assign(d=np.where(t[kol] <= q1, 0, np.where(t[kol] <= q2, 1, 2)))
    r = {"etken": kol}
    for dn in ("IS", "OOS"):
        for g in (0, 1, 2):
            x = t[(t.donem == dn) & (t.d == g)].sonuc_r
            r[f"{dn}{g}"] = round(x.mean(), 3) if len(x) else np.nan
    for dn in ("IS", "OOS"):
        x = t[t.donem == dn]
        r[f"rho_{dn}"] = round(x[kol].corr(x.sonuc_r, method="spearman"), 3)
    r["tutarli"] = np.sign(r["rho_IS"]) == np.sign(r["rho_OOS"]) and min(abs(r["rho_IS"]), abs(r["rho_OOS"])) >= 0.05
    return r


def ozet(x):
    if len(x) == 0:
        return "-"
    return f"{len(x)} isl %{100 * (x.sonuc_r > 0).mean():.1f} {x.sonuc_r.sum():+.1f}R ({x.sonuc_r.mean():+.3f})"


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    tick = veri._get("/api/v3/ticker/24hr", {})
    haric = set(COINLER) | A.STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                          "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                          "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
    aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
            and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
    aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    yeni = [d["symbol"] for d in aday[:70]]
    A.DATA["btc_d"] = veri.mumlar_onbellekli("BTCUSDT", "1d", "2019-06-01")
    A.DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", A.VERI_BAS)
    A.DATA["4h"] = A.yukle(COINLER + yeni)
    yeni = [s for s in yeni if s in A.DATA["4h"]]
    with mp.Pool(4) as hv:
        tr = A.calistir(B, COINLER + yeni, "4h", hv)
    tr = tr.reset_index(drop=True)
    tr["donem"] = np.where(pd.to_datetime(tr.giris_zaman) >= pd.Timestamp(A.OOS_BAS), "OOS", "IS")
    tr["grup"] = np.where(tr.symbol.isin(COINLER), "46", "YENI")
    print("islem", len(tr), round(time.time() - t0), flush=True)

    F = {s: coin_ozellik(A.DATA["4h"][s][0]) for s in A.DATA["4h"]}
    btc = coin_ozellik(A.DATA["btc_4h"])
    btc_d = A.DATA["btc_d"]; bdc = btc_d["close"].to_numpy(float)
    btc_e200 = pd.Series(bdc / k.ema(bdc, 200) - 1, index=pd.to_datetime(btc_d["open_time"])).shift(1)
    genis = pd.concat({s: f["ust50"] for s, f in F.items()}, axis=1).mean(axis=1)

    rows = []
    for idx, r in tr.iterrows():
        f = F.get(r.symbol)
        t = pd.Timestamp(r.giris_zaman)
        if f is None or t not in f.index:
            continue
        i = f.index.get_loc(t)
        y = r.yon
        x = f.iloc[i]; xp = f.iloc[i - 1]
        a = x.atr
        lvl = x.hh80 if y == 1 else x.ll80
        bt = btc.loc[t] if t in btc.index else None
        rng = x.h - x.l
        o_ = {"idx": idx,
              "rs7": y * (x.ret42 - (bt.ret42 if bt is not None else np.nan)),
              "rs30": y * (x.ret180 - (bt.ret180 if bt is not None else np.nan)),
              "genislik": genis.get(t, np.nan) if y == 1 else 1 - genis.get(t, np.nan),
              "sikisma_atr": xp.sq, "sikisma_bb": xp.bbw_pct,
              "hacim_x": x.v / x.vort if x.vort > 0 else np.nan,
              "kapanis_gucu": ((x.c - x.l) / rng if y == 1 else (x.h - x.c) / rng) if rng > 0 else np.nan,
              "kirilim_atr": y * (x.c - lvl) / a if a > 0 else np.nan,
              "stop_atr": abs(r.giris - r.stop_ilk) / a if a > 0 else np.nan,
              "risk_pct": abs(r.giris - r.stop_ilk) / r.giris * 100,
              "rsi_y": x.rsi if y == 1 else 100 - x.rsi, "adx": x.adx,
              "ema21_atr": y * (x.c - x.e21) / a if a > 0 else np.nan,
              "mum_atr": rng / a if a > 0 else np.nan,
              "btc_trend_y": y * btc_e200.asof(t) if len(btc_e200) else np.nan,
              "saat": (t + pd.Timedelta(hours=4)).hour, "haftagunu": t.dayofweek,
              "tp1_r": abs(r.tp1 - r.giris) / abs(r.giris - r.stop_ilk), "yon": y}
        rows.append(o_)
    oz = pd.DataFrame(rows).set_index("idx")
    tr = tr.join(oz.drop(columns=["yon"]))
    tr.to_csv(f"{OUT}/dogruluk_islemler.csv", index=False)
    kol = [c_ for c_ in oz.columns if c_ not in ("yon",)]

    rap = [f"Toplam {len(tr)} islem | IS {ozet(tr[tr.donem == 'IS'])} | OOS {ozet(tr[tr.donem == 'OOS'])}", ""]
    tt = [tercil(tr, c_) for c_ in kol]
    rap.append("=== Tercil (ortalama R; 0=dusuk, 2=yuksek; IS sinirlari) ===")
    rap.append(pd.DataFrame([x for x in tt if x]).to_string(index=False))
    for yad, yv in (("LONG", 1), ("SHORT", -1)):
        tt = [tercil(tr[tr.yon == yv], c_) for c_ in kol]
        rap.append(f"\n=== Tercil [{yad}] ===")
        rap.append(pd.DataFrame([x for x in tt if x]).to_string(index=False))

    # --- meta-etiketleme: IS'te egit, OOS'ta sina
    d = tr.dropna(subset=kol).copy()
    d["yon_f"] = d.yon
    X = kol + ["yon_f"]
    IS = d[d.donem == "IS"]; OOS = d[d.donem == "OOS"]
    yIS = (IS.sonuc_r > 0).astype(int); yOOS = (OOS.sonuc_r > 0).astype(int)
    rap.append(f"\n=== META-ETIKETLEME (IS {len(IS)} islemde egitim, OOS {len(OOS)} islemde sinama) ===")
    modeller = {
        "lojistik": make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)),
        "agac(GBM sig)": GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=1),
    }
    for ad, m in modeller.items():
        m.fit(IS[X], yIS)
        pIS = m.predict_proba(IS[X])[:, 1]; pO = m.predict_proba(OOS[X])[:, 1]
        auc_is = roc_auc_score(yIS, pIS); auc_o = roc_auc_score(yOOS, pO)
        rap.append(f"{ad}: AUC IS {auc_is:.3f} | OOS {auc_o:.3f}  (0.5 = tesaduf)")
        for q in (0.25, 0.33, 0.5):
            esik = np.quantile(pIS, q)
            tut = OOS[pO >= esik]; at = OOS[pO < esik]
            rap.append(f"   OOS: IS'teki en dusuk %{int(q * 100)} puan esigi altini ele -> tutulan {ozet(tut)} | elenen {ozet(at)} | once {ozet(OOS)}")
            for g in ("46", "YENI"):
                o2 = OOS[OOS.grup == g]; p2 = pO[(OOS.grup == g).to_numpy()]
                rap.append(f"      [{g}] tutulan {ozet(o2[p2 >= esik])} | elenen {ozet(o2[p2 < esik])}")
        if ad == "lojistik":
            coef = m.named_steps["logisticregression"].coef_[0]
            rap.append("   katsayilar: " + ", ".join(f"{c_} {v_:+.2f}" for c_, v_ in sorted(zip(X, coef), key=lambda z: -abs(z[1]))))
    with open(f"{OUT}/dogruluk.txt", "w") as f:
        f.write("\n".join(rap))
    print("\n".join(rap[:3]), flush=True)
    print("bitti", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
