"""
K69 SHORT - dusuk hacimli retest short (Ekim 2026 arastirmasi, short_lab.retest_olaylari ile ayni kural).

Kural (4 saatlik, USDT-M vadeli):
  1) Kapanis, son N mumun (N = 80 veya 160) en dusugunun 0.05 ATR altinda VE hacim >= 1.5 x ortalama  -> destek kirildi
  2) 2..30 mum icinde fiyat kirilan seviyeye geri yukselir: mumun tepesi seviyenin 0.2 ATR yakininda,
     kapanis seviyenin altinda, mum kirmizi
  3) Bu yukselis dusuk hacimli: son 3 mumun ortalama hacmi < 0.7 x ortalama, ret mumundan onceki 2 mum yesil
  4) Kirilim mumu asiri buyuk degil (< 2.7 ATR)
  5) Coin gunde >= 1 milyon $ islem goruyor (son 30 gunun medyani)
  Giris: ret mumunun kapanisi. Stop: max(seviye, mum tepesi) + 0.8 ATR. Hedef: 0.5R (tamamen kapat). Zaman stopu: 30 mum.
  Etiket (coin >= 5M$ ise): destek kirilmadan once 3+ kez test edildiyse ⭐⭐, 2 kez ise ⭐; digerleri yildizsiz.
Test (2020-10/2026, 656 vadeli sozlesme, delist olanlar dahil, maliyet %0.2): 822 islem, isabet %81.5, islem basi +0.18R;
son 12 ay haftada ~4.3 sinyal, isabet %75. (23 Eki 2026: sinyal sayisi icin destek test sarti kaldirildi, hacim siniri 5M -> 2M -> 1M;
1M ile: 936 islem, isabet %80.3, son 12 ay haftada ~6.2 sinyal, isabet %74.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

AYAR = {
    "seviyeler": (80, 160),
    "kirilim_hacim": 1.5,
    "min_bar": 2,
    "maks_bekle": 30,
    "yakin_atr": 0.2,
    "stop_atr": 0.8,
    "hedef_r": 0.5,
    "zaman_stopu": 30,
    "dusuk_hacim": 0.7,
    "min_dokunus": 0,
    "guclu_dokunus": 3,
    "maks_kirilim_boy": 2.7,
    "min_hacim_usd": 1e6,
    "yildiz_hacim_usd": 5e6,          # yildiz icin coin en az bu kadar likit olmali
}


def gostergeler(g: pd.DataFrame) -> dict:
    """g: open_time indeksli o,h,l,c,v (sadece kapanmis 4s mumlar)."""
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    va = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    qv = (pd.Series(c * v).rolling(180, min_periods=60).median() * 6).to_numpy()
    return {"o": o, "h": h, "l": l, "c": c, "v": v, "atr": atr, "va": va, "qv": qv}


def sinyaller(g: pd.DataFrame, A: dict | None = None) -> list[dict]:
    """Tum gecmisteki retest short sinyalleri (kurallari gecenler). Her eleman: zaman (sinyal mumu acilisi), giris, stop, hedef, ..."""
    A = dict(AYAR, **(A or {}))
    x = gostergeler(g)
    o, h, l, c, v, atr, va, q = (x[k] for k in ("o", "h", "l", "c", "v", "atr", "va", "qv"))
    T = g.index
    n = len(c)
    out = {}
    for R_ in A["seviyeler"]:
        ll = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
        sev = np.nan
        k = -1
        kir_v = np.nan
        i = R_ + 1
        while i < n:
            if np.isnan(sev):
                if c[i] < ll[i] - 0.05 * atr[i] and v[i] >= A["kirilim_hacim"] * va[i] and q[i] >= A["min_hacim_usd"]:
                    k, sev, kir_v = i, ll[i], v[i] / va[i]
                i += 1
                continue
            a = atr[i]
            if i - k > A["maks_bekle"] or c[i] > sev + 0.5 * a:
                sev = np.nan
                continue                       # ayni mum yeni kirilim olarak tekrar degerlendirilir
            if i - k >= A["min_bar"] and h[i] >= sev - A["yakin_atr"] * a and c[i] < sev and c[i] < o[i] \
                    and q[i] >= A["min_hacim_usd"]:
                st = max(sev, h[i]) + A["stop_atr"] * a
                e = c[i]
                risk = (st - e) / e
                ka = atr[k]
                dokunus = int((l[max(0, k - R_):k] <= sev + 0.3 * ka).sum())
                kir_boy = (h[k] - l[k]) / ka
                vor3 = v[i - 2:i + 1].mean() / va[i]
                kirmizi3 = int((c[i - 2:i + 1] < o[i - 2:i + 1]).sum())
                if (0.004 <= risk <= 0.25 and vor3 < A["dusuk_hacim"] and kirmizi3 == 1
                        and dokunus >= A["min_dokunus"] and kir_boy < A["maks_kirilim_boy"]):
                    s = {"zaman": T[i], "ix": i, "giris": e, "stop": st, "hedef": e - A["hedef_r"] * (st - e),
                         "seviye": sev, "kirilim_zaman": T[k], "dokunus": dokunus, "kirilim_boy": kir_boy,
                         "hacim_orani": vor3, "kirilim_hacim": kir_v, "seviye_mum": R_, "risk_pct": risk * 100,
                         "gunluk_hacim": q[i], "guclu": dokunus >= A["guclu_dokunus"],
                         "yildiz": (2 if dokunus >= A["guclu_dokunus"] else 1 if dokunus >= 2 else 0)
                         if q[i] >= A["yildiz_hacim_usd"] else 0}
                    eski = out.get(T[i])
                    if eski is None or s["dokunus"] > eski["dokunus"]:
                        out[T[i]] = s
                sev = np.nan               # seviye basina tek retest
            i += 1
    return [out[t] for t in sorted(out)]


def sonuc_takip(g: pd.DataFrame, poz: dict, A: dict | None = None):
    """Acik short'u giris mumundan sonraki kapanmis mumlarla kontrol et. Donus: None (acik) ya da (neden, fiyat, zaman, R)."""
    A = dict(AYAR, **(A or {}))
    gz = pd.Timestamp(poz["zaman"])
    sonra = g[g.index > gz]
    e, st, tg = poz["giris"], poz["stop"], poz["hedef"]
    for j, (t, r) in enumerate(sonra.iterrows(), start=1):
        if r["h"] >= st:                    # ayni mumda ikisi de degdiyse stop sayilir (kotumser, testle ayni)
            return "STOP", st, t, (e - st) / (st - e)
        if r["l"] <= tg:
            return "HEDEF", tg, t, (e - tg) / (st - e)
        if j >= A["zaman_stopu"]:
            return "ZAMAN", r["c"], t, (e - r["c"]) / (st - e)
    return None


def bekleyenler(g: pd.DataFrame, A: dict | None = None) -> list[dict]:
    """Su an retest beklenen kirilimlar (sinyaller() ile ayni durum makinesi; son mumda hala aktif olan seviyeler).
    Kirilim mumu asiri buyukse (sinyal veremeyecegi icin) listelenmez."""
    A = dict(AYAR, **(A or {}))
    x = gostergeler(g)
    o, h, l, c, v, atr, va, q = (x[k] for k in ("o", "h", "l", "c", "v", "atr", "va", "qv"))
    T = g.index
    n = len(c)
    out = []
    for R_ in A["seviyeler"]:
        ll = pd.Series(l).rolling(R_).min().shift(1).to_numpy()
        sev, k = np.nan, -1
        i = R_ + 1
        while i < n:
            if np.isnan(sev):
                if c[i] < ll[i] - 0.05 * atr[i] and v[i] >= A["kirilim_hacim"] * va[i] and q[i] >= A["min_hacim_usd"]:
                    k, sev = i, ll[i]
                i += 1
                continue
            a = atr[i]
            if i - k > A["maks_bekle"] or c[i] > sev + 0.5 * a:
                sev = np.nan
                continue
            if i - k >= A["min_bar"] and h[i] >= sev - A["yakin_atr"] * a and c[i] < sev and c[i] < o[i] \
                    and q[i] >= A["min_hacim_usd"]:
                sev = np.nan
            i += 1
        if not np.isnan(sev):
            ka = atr[k]
            boy = (h[k] - l[k]) / ka
            if boy >= A["maks_kirilim_boy"]:
                continue
            dok = int((l[max(0, k - R_):k] <= sev + 0.3 * ka).sum())
            yildiz = (2 if dok >= A["guclu_dokunus"] else 1 if dok >= 2 else 0) if q[-1] >= A["yildiz_hacim_usd"] else 0
            out.append({"seviye": sev, "kirilim_zaman": T[k], "kalan_mum": A["maks_bekle"] - (n - 1 - k), "dokunus": dok,
                        "yildiz": yildiz, "son_fiyat": c[-1], "uzaklik_pct": (sev / c[-1] - 1) * 100, "seviye_mum": R_,
                        "gunluk_hacim": q[-1]})
    if len(out) > 1:
        out = [max(out, key=lambda d: d["dokunus"])]
    return out
