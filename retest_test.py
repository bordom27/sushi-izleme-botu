"""
Kullanicinin "Kirilim-Retest Test" Pine stratejisinin birebir Python simulasyonu (TradingView emir mantigi):
  - Kirilim: pozisyon yok ve beklemiyorken, kapanis > onceki 20 mumun en yuksegi, bant genisligi <= %40, hacim > 1.5 x SMA20
  - Retest: kirilimdan sonraki mumlarda low <= seviye x 1.03 ve kapanis > seviye  -> sonraki mumun ACILISINDA long
  - Iptal: kapanis < bant dibi veya 8 mumdan fazla gecti
  - Stop: bant dibi x 0.98; TP1: sinyal kapanisi + 2 x (kapanis - stop), pozisyonun %50'si
  - TP1 sonrasi stop = max(stop, giris, son 5 mumun dibi) (mum kapanisinda guncellenir, sonraki mumda gecerli)
  - Mum ici sira: acilis tepeye yakinsa once tepe, sonra dip (TradingView varsayimi); bosluklu acilista stop acilistan dolar
  - Komisyon %0.05 / taraf; pozisyon = sermayenin %10'u (strateji varsayilani)
Cikti: arastirma_cikti/retest_<tf>.csv (donem ozetleri) + islem listesi
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import time

import numpy as np
import pandas as pd

import veri

OUT = "arastirma_cikti"
P = dict(baseLen=20, maxWidth=40.0, useVol=True, volMult=1.5, retestTol=3.0, retestWin=8, slBuf=2.0, tp1R=2.0,
         tp1Pct=50, trailLen=5, kom=0.0005)


def sim(sym: str, df: pd.DataFrame, p=P) -> list[dict]:
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float); v = df["volume"].to_numpy(float); t = df["open_time"].to_numpy()
    n = len(c); L = p["baseLen"]
    rh = pd.Series(h).rolling(L).max().shift(1).to_numpy()
    rl = pd.Series(l).rolling(L).min().shift(1).to_numpy()
    vsma = pd.Series(v).rolling(20).mean().to_numpy()
    trail = pd.Series(l).rolling(p["trailLen"]).min().shift(1).to_numpy()
    out = []
    waiting = False; lvl = bl = np.nan; brk = -1
    pos = None          # dict: giris, sl, tp1, kalan, tp1Hit, bar, zaman, risk
    bekleyen = None     # retest sinyali -> sonraki mum acilisinda giris
    for i in range(n):
        # --- 0) bekleyen giris emri bu mumun acilisinda dolar
        if bekleyen is not None and pos is None:
            e = o[i]
            pos = dict(giris=e, sl=bekleyen["sl"], tp1=bekleyen["tp1"], kalan=1.0, tp1Hit=False, bar=i, zaman=t[i],
                       risk=e - bekleyen["sl"], pnl=0.0, gerc=[])
            bekleyen = None
        # --- 1) pozisyon varsa mum ici cikislar (bu mumda gecerli stop/tp: onceki mum kapanisinda belirlenen)
        if pos is not None:
            sl, tp = pos["sl"], pos["tp1"]
            tepe_once = abs(o[i] - h[i]) < abs(o[i] - l[i])
            def kapat(fiyat, oran, neden):
                pos["pnl"] += oran * (fiyat - pos["giris"]) / pos["giris"] - oran * p["kom"] * (1 + fiyat / pos["giris"])
                pos["kalan"] -= oran
                pos["gerc"].append(neden)
            if o[i] <= sl:                                   # bosluklu acilis stopun altinda
                kapat(o[i], pos["kalan"], "STOP")
            else:
                sira = ["H", "L"] if tepe_once else ["L", "H"]
                for adim in sira:
                    if pos["kalan"] <= 1e-9:
                        break
                    if adim == "H" and not pos["tp1Hit"] and h[i] >= tp:
                        kapat(max(tp, o[i]), p["tp1Pct"] / 100.0, "TP1")
                        pos["tp1Hit"] = True
                    if adim == "L" and l[i] <= sl:
                        kapat(sl, pos["kalan"], "STOP_TP1" if pos["tp1Hit"] else "STOP")
            if pos["kalan"] <= 1e-9:
                r_ = pos["pnl"] * pos["giris"] / pos["risk"] if pos["risk"] > 0 else np.nan
                out.append(dict(symbol=sym, giris_zaman=pd.Timestamp(pos["zaman"]), cikis_zaman=pd.Timestamp(t[i]),
                                getiri=pos["pnl"], sonuc_r=r_, tp1=pos["tp1Hit"], bar=i - pos["bar"],
                                risk_pct=pos["risk"] / pos["giris"] * 100))
                pos = None
            else:
                # kapanista stop guncelle (TP1 sonrasi basabas + iz suren)
                if pos["tp1Hit"]:
                    tr = trail[i] if not np.isnan(trail[i]) else -np.inf
                    pos["sl"] = max(pos["sl"], pos["giris"], tr)
        if np.isnan(rh[i]) or np.isnan(vsma[i]):
            continue
        # --- 2) kirilim (pozisyon yok, beklemiyor)
        width = (rh[i] - rl[i]) / rl[i] * 100 if rl[i] > 0 else np.inf
        vol_ok = (not p["useVol"]) or v[i] > vsma[i] * p["volMult"]
        flat = pos is None and bekleyen is None
        if flat and not waiting and c[i] > rh[i] and width <= p["maxWidth"] and vol_ok:
            waiting = True; lvl = rh[i]; bl = rl[i]; brk = i
        retest = waiting and i > brk and l[i] <= lvl * (1 + p["retestTol"] / 100) and c[i] > lvl
        invalid = waiting and (c[i] < bl or i - brk > p["retestWin"])
        if retest and flat:
            sl = bl * (1 - p["slBuf"] / 100)
            if c[i] > sl:
                bekleyen = dict(sl=sl, tp1=c[i] + (c[i] - sl) * p["tp1R"])
            waiting = False
        elif invalid:
            waiting = False
    return out


def _is(a):
    s, iv, bas = a
    try:
        df = veri.mumlar_onbellekli(s, iv, bas)
        if len(df) < 60:
            return []
        return sim(s, df)
    except Exception as exc:
        print("hata", s, exc, flush=True)
        return []


def main():
    iv = sys.argv[1]
    bas = {"1h": "2023-09-01", "4h": "2019-09-01", "1d": "2019-06-01", "1w": "2019-06-01"}[iv]
    tick = veri._get("/api/v3/ticker/24hr", {})
    from coin_listesi import COINLER
    haric = set(COINLER) | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT", "RLUSDUSDT", "USD1USDT",
                            "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT", "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT",
                            "USDEUSDT", "PAXGUSDT"}
    aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
            and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR")) and not d["symbol"].endswith("BUSDT")]
    aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    liste = list(COINLER) + [d["symbol"] for d in aday[:70]]
    # veriyi sirayla indir (onbellek), sonra paralel simule et
    for s in liste:
        try:
            veri.mumlar_onbellekli(s, iv, bas)
        except Exception as exc:
            print("veri yok", s, exc, flush=True)
        time.sleep(0.05)
    with mp.Pool(4) as hv:
        sonuc = hv.map(_is, [(s, iv, bas) for s in liste])
    tr = pd.DataFrame([x for lst in sonuc for x in lst])
    tr.to_csv(f"{OUT}/retest_islem_{iv}.csv.gz", index=False, compression="gzip")
    DON = [("Y2020", "2020-01-01", "2020-12-31 23:59"), ("Y2021", "2021-01-01", "2021-12-31 23:59"),
           ("Y2022", "2022-01-01", "2022-12-31 23:59"), ("Y2023", "2023-01-01", "2023-12-31 23:59"),
           ("Y24a", "2024-01-01", "2024-06-30 23:59"), ("A", "2024-07-01", "2025-06-30 23:59"),
           ("B", "2025-07-01", "2026-02-28 23:59"), ("C", "2026-03-01", None), ("TUM", "2020-01-01", None)]
    rows = []
    for dk, b, e in DON:
        x = tr[(tr.giris_zaman >= pd.Timestamp(b)) & ((tr.giris_zaman <= pd.Timestamp(e)) if e else True)] if len(tr) else tr
        if len(x) == 0:
            rows.append(dict(donem=dk, n=0)); continue
        eq = x.sort_values("cikis_zaman").sonuc_r.cumsum()
        rows.append(dict(donem=dk, n=len(x), isabet=round(100 * (x.getiri > 0).mean(), 1),
                         ort_getiri_pct=round(100 * x.getiri.mean(), 2), R=round(x.sonuc_r.sum(), 1),
                         R_islem=round(x.sonuc_r.mean(), 3), maxdd_R=round((eq.cummax().clip(lower=0) - eq).max(), 1),
                         ort_risk_pct=round(x.risk_pct.median(), 1), tp1_orani=round(100 * x.tp1.mean()),
                         ort_bar=round(x.bar.mean(), 1), sermaye10_pct=round(100 * (0.10 * x.getiri).sum(), 1)))
    d = pd.DataFrame(rows)
    d.to_csv(f"{OUT}/retest_{iv}.csv", index=False)
    print(d.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
