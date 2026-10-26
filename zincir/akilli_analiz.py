"""
Akilli para arastirmasi - adim 2 (yerel): erken alip pump sonrasi satan cuzdanlar sonraki pump'lari onceden haber veriyor mu?
Yuruyen test: her pencere (olay/kontrol) icin, o andan ONCE tamamlanmis pump'larda >= k farkli coinde 'erken karli' olmus
cuzdanlar (akilli set) belirlenir; bu cuzdanlardan biri pencerenin son 48s'inde (veya 7 gununde) net alim yaptiysa 'isabet'.
Isabet orani olay vs kontrol karsilastirilir (olabilirlik orani).
"""
import glob, sys
import numpy as np, pandas as pd

D = "arastirma_cikti/zincir/akilli"
W = pd.read_csv("zincir/akilli_pencereler.csv", parse_dates=["t"]); W["pid"] = W.index
P = pd.concat([pd.read_csv(f) for f in glob.glob(f"{D}/pencere_*.csv")])
C = pd.concat([pd.read_csv(f) for f in glob.glob(f"{D}/cuzdan_*.csv")])
C["adres"] = C.adres.str.lower()
gecerli = set(P[P["not"].fillna("") == ""].pid) & set(C.pid)
W = W[W.pid.isin(gecerli)].copy()
C = C[C.pid.isin(gecerli)].merge(W[["pid", "symbol", "zincir", "t", "tip"]], on="pid")
print("gecerli pencere:", W.groupby(["zincir", "tip"]).size().to_dict())
pd.set_option("display.width", 220)


def akilli_olaylar(on_min, sat_oran):
    E = C[(C.tip == "olay") & (C.on >= on_min) & (C.sonra <= -sat_oran * C.on)]
    return E[["adres", "symbol", "t"]].assign(bitis=E.t + pd.Timedelta(days=3))


def test(on_min=0.005, sat_oran=0.5, k=2, alim_min=0.001, alan="on48", bas="2025-07-01"):
    E = akilli_olaylar(on_min, sat_oran).sort_values("bitis")
    sonuc = []
    for _, w in W[W.t >= bas].iterrows():
        gecmis = E[E.bitis < w.t]
        say = gecmis.groupby("adres").symbol.nunique()
        S = set(say[say >= k].index)
        a = C[(C.pid == w.pid) & (C[alan] >= alim_min)]
        hit = a[a.adres.isin(S)]
        sonuc.append({"pid": w.pid, "tip": w.tip, "zincir": w.zincir, "S": len(S), "isabet": int(len(hit) > 0),
                      "isabet_say": len(hit), "pay": hit[alan].sum()})
    R = pd.DataFrame(sonuc)
    o = R[R.tip == "olay"].isabet.mean(); c = R[R.tip == "kontrol"].isabet.mean()
    return R, o, c


if __name__ == "__main__":
    E = akilli_olaylar(0.005, 0.5)
    say = E.groupby("adres").symbol.nunique()
    print("erken-karli kayit:", len(E), "| cuzdan:", len(say), "| >=2 coinde:", (say >= 2).sum(), "| >=3:", (say >= 3).sum())
    rows = []
    for on_min in (0.002, 0.005, 0.01):
        for k in (2, 3):
            for alan, am in (("on48", 0.001), ("on48", 0.003), ("on", 0.003)):
                R, o, c = test(on_min, 0.5, k, am, alan)
                rows.append({"on_min": on_min, "k": k, "alan": alan, "alim_min": am, "ort_S": R.S.mean(),
                             "olay_n": (R.tip == "olay").sum(), "kontrol_n": (R.tip == "kontrol").sum(),
                             "olay_isabet": o, "kontrol_isabet": c, "oran": o / c if c else np.nan})
    print(pd.DataFrame(rows).round(3).to_string())


def test_secici(on_min=0.005, sat_oran=0.5, k=2, kesinlik=0.5, alim_min=0.001, alan="on48", bas="2025-07-01"):
    """Akilli set: gecmiste >= k coinde erken-karli VE gorundugu pencerelerin (olay+kontrol, alim yapmis) >= kesinlik kadarinda karli.
    (Her yerde alim yapan bot / piyasa yapici / toplayici cuzdanlari eler.)"""
    C2 = C.copy()
    C2["karli"] = (C2.tip == "olay") & (C2.on >= on_min) & (C2.sonra <= -sat_oran * C2.on)
    C2["gor"] = C2.on >= on_min
    C2["bitis"] = C2.t + pd.to_timedelta(np.where(C2.tip == "olay", 3, 0), unit="D")
    sonuc = []
    for _, w in W[W.t >= bas].iterrows():
        g = C2[C2.bitis < w.t]
        st = g.groupby("adres").agg(k_=("karli", "sum"), gor=("gor", "sum"))
        ks = g[g.karli].groupby("adres").symbol.nunique()
        st["coin"] = ks.reindex(st.index).fillna(0)
        S = set(st[(st.coin >= k) & (st.k_ / st.gor.clip(lower=1) >= kesinlik)].index)
        a = C2[(C2.pid == w.pid) & (C2[alan] >= alim_min)]
        hit = a[a.adres.isin(S)]
        sonuc.append({"tip": w.tip, "S": len(S), "isabet": int(len(hit) > 0)})
    R = pd.DataFrame(sonuc)
    return R, R[R.tip == "olay"].isabet.mean(), R[R.tip == "kontrol"].isabet.mean()


def secici_tablo():
    rows = []
    for on_min in (0.002, 0.005):
        for k in (2, 3):
            for kes in (0.3, 0.5, 0.7):
                for alan, am in (("on48", 0.001), ("on", 0.003)):
                    R, o, c = test_secici(on_min, 0.5, k, kes, am, alan)
                    rows.append({"on_min": on_min, "k": k, "kesinlik": kes, "alan": alan, "ort_S": R.S.mean(),
                                 "olay_isabet": o, "kontrol_isabet": c, "oran": o / c if c else np.nan})
    print(pd.DataFrame(rows).round(3).to_string())
