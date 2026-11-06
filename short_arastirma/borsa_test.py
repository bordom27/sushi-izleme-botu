"""
K69 SHORT hisselerde (6 Kas 2026). veri_borsa.py ciktisi: arastirma_cikti/borsa/
  gunluk: 2000 -> bugun (BIST + S&P 500), kural mum sayilariyla aynen (80/160 mumluk dip, 2-30 mum retest, 30 mum zaman stopu)
  4s    : son ~2 yil, 1s mumlardan (gun icinde 4'er saatlik bloklar)
Likidite: gunluk islem hacmi >= 1M$ (BIST: USD/TRY ile dolara). Kume: ayni mumda ayni piyasada kac hissede sinyal.
Kurallar: CANLI (onceki 2 mum yesil, kume>=3 | 2 yildiz), YENI (onceki 2 mumdan >=1 yesil, kume>=6, tek 2 yildiz yok).
Maliyet %0.2, funding yok (hisse odunc maliyeti hesaba katilmadi). Hayatta kalma yanliligi: sadece bugun islem goren hisseler.
Kullanim: SP=... python short_arastirma/borsa_test.py
"""
from __future__ import annotations

import glob
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_arastirma.gelistir2 as G                                    # noqa: E402

SP = os.environ.get("SP", "/tmp")
B = "arastirma_cikti/borsa"


def yukle(on):
    K = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{B}/{on}_*.csv.gz"))], ignore_index=True)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    kur = None
    if os.path.exists(f"{B}/usdtry.csv.gz"):
        u = pd.read_csv(f"{B}/usdtry.csv.gz")
        kur = pd.Series(u.c.values, index=pd.to_datetime(u.t, unit="s").dt.normalize()).sort_index()
        kur = kur[~kur.index.duplicated()]
    D = {}
    for (s, p), g in K.groupby(["symbol", "piyasa"]):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]].astype(float).dropna()
        if on == "gun":
            g.index = g.index.normalize()
            g = g[~g.index.duplicated(keep="last")]
        if on == "saat":
            # 1s -> 4s: her gun icinde ilk 4 saat / sonraki saatler
            gun = g.index.normalize()
            sira = g.groupby(gun).cumcount() // 4
            anahtar = gun + pd.to_timedelta(sira * 4, unit="h")
            g = g.groupby(anahtar).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"))
        g = g[(g.v > 0) & (g.h >= g.l)]
        if len(g) < 250 or s.startswith("^") or s == "XU100.IS":
            continue
        if p == "BIST":
            if kur is None:
                continue
            k = pd.Series(kur.reindex(g.index.normalize(), method="ffill").to_numpy()).bfill().fillna(kur.iloc[0]).to_numpy()
            g["v"] = g.v / k                       # hacmi dolar karsiligina cevir (fiyat TL kalir, q = c*v dolar olur)
        # short_retest gunluk hacmi 4s mum x 6 diye hesaplar: gunluk mumda /6, borsa 4s'inde (gunde ~2 blok) /3
        g["v"] = g.v / (6 if on == "gun" else 3)
        D[(s, p)] = g
    return D


def calistir(on, olcek):
    D = yukle(on)
    print(f"[{on}] {len(D)} hisse:", pd.Series([p for _, p in D]).value_counts().to_dict(),
          min(g.index[0] for g in D.values()), "->", max(g.index[-1] for g in D.values()))
    sonuc = []
    for piyasa in ("BIST", "ABD"):
        Dp = {s: g for (s, p), g in D.items() if p == piyasa}
        idx = [g.c for g in Dp.values()]
        endeks = pd.concat(idx, axis=1).pct_change().mean(axis=1).fillna(0).add(1).cumprod()   # esit agirlikli piyasa (BTC yerine)
        G.D, G.FR, G.BTC = Dp, {}, endeks
        with mp.get_context("fork").Pool(2) as hv:
            out = hv.map(G.coin, list(Dp))
        t = pd.DataFrame([x for o in out for x in o])
        if not len(t):
            continue
        t = t.sort_values("dokunus").drop_duplicates(["symbol", "zaman"], keep="last")
        t["yildiz"] = np.where(t.q >= 5e6, np.where(t.dokunus >= 3, 2, np.where(t.dokunus >= 2, 1, 0)), 0)
        t["piyasa"] = piyasa
        sonuc.append(t)
    t = pd.concat(sonuc)
    t.to_pickle(os.path.join(SP, f"borsa_{on}.pkl"))
    return t


def kurallar(t):
    sert = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7)
    e1, e2 = sert & (t.kirmizi3 == 1), sert & (t.kirmizi3 <= 2)
    k1 = t.zaman.map(t[e1].groupby("zaman").size()).fillna(0)
    k2 = t.zaman.map(t[e2].groupby("zaman").size()).fillna(0)
    return {"ham (filtresiz)": e1, "CANLI": e1 & ((k1 >= 3) | (t.yildiz == 2)), "YENI": e2 & (k2 >= 6)}


def rapor(t, on):
    f = lambda r: f"{len(r)}/%{(r > 0).mean() * 100:.0f}/{r.sum():+.0f}R" if len(r) else "-"
    for piyasa, tp in t.groupby("piyasa"):
        print(f"\n== {on} {piyasa}")
        for k, m in kurallar(tp).items():
            x = G.tek_pozisyon(tp[m]).dropna(subset=["R"])
            if not len(x):
                print(f"  {k}: islem yok")
                continue
            gun = x.groupby(x.cikis.dt.floor("D")).R.sum().sort_index(); eq = gun.cumsum()
            print(f"  {k:16s} n={len(x)} isabet %{(x.R > 0).mean() * 100:.1f} R/i {x.R.mean():+.3f} toplam {x.R.sum():+.0f}R "
                  f"maxDD {(eq.cummax() - eq).max():.1f}R")
            print("     " + " ".join(f"{y}:{f(b.R)}" for y, b in x.groupby(x.zaman.dt.year)))


if __name__ == "__main__":
    for on in sys.argv[1:] or ["gun", "saat"]:
        if not glob.glob(f"{B}/{on}_*.csv.gz"):
            print(on, "verisi yok")
            continue
        t = calistir(on, 1)
        rapor(t, on)
