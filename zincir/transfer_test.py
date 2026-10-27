"""
Dump/pump oncesi transfer testi (GitHub Actions): borsa yatirmalari ve tek cuzdandan yeni cuzdanlara dagitim.
Pencere [t-5g, t): taban = ilk 3 gun, son = son 48 saat. t = olaydan onceki son 4s mum kapanisi.
Borsa (CEX) tespiti etiketsiz 'supurme' kalibiyla: yatirma adresi D -> az kaynaktan alir (H'den degil), ciktisinin >= %90'ini
tek bir H'ye gonderir; >= 5 yatirma adresi supuren H = borsa sicak cuzdani.
Kullanim: python zincir/transfer_test.py <zincir> <parca> <toplam>   (girdi: zincir/transfer_pencereler.csv)
Cikti: arastirma_cikti/zincir/transfer/ozellik_<zincir>_<parca>.csv (kaldigi yerden devam)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from zincir import rpc, akilli

OUTD = "arastirma_cikti/zincir/transfer"
SURE = float(os.environ.get("MAKS_DAKIKA", "320")) * 60
akilli.MAKS_TX = 150_000


def borsa_bul(T):
    out = T.groupby("kimden").m.sum()
    inn = T.groupby("kime").m.sum()
    gonderen_say = T.groupby("kime").kimden.nunique()
    hedef = T.groupby(["kimden", "kime"]).m.sum().reset_index().sort_values("m", ascending=False).drop_duplicates("kimden")
    hedef = hedef.set_index("kimden")
    hedef["pay"] = hedef.m / out.reindex(hedef.index)
    # D'nin H'den aldigi
    hd = T.groupby(["kime", "kimden"]).m.sum()
    aday = hedef[(hedef.pay >= 0.9)]
    aday = aday[gonderen_say.reindex(aday.index).fillna(0) <= 3]
    aday = aday[out.reindex(aday.index) >= 0.8 * inn.reindex(aday.index).fillna(0)]
    hden = np.array([hd.get((d, h), 0.0) for d, h in zip(aday.index, aday.kime)])
    aday = aday[hden <= 0.1 * inn.reindex(aday.index).fillna(0).to_numpy() + 1e-12]
    say = aday.groupby("kime").size()
    H = set(say[say >= 5].index)
    D = set(aday[aday.kime.isin(H)].index)
    return H, D


def ozellik(T, t):
    T = T[(T.kimden != T.kime)].copy()
    T["m"] = T.ham.astype(float)
    T["t"] = pd.to_datetime(T.ts, unit="s")
    T = T[(T.t >= t - pd.Timedelta(days=5)) & (T.t < t)]
    b = T[T.t < t - pd.Timedelta(days=2)]; s = T[T.t >= t - pd.Timedelta(days=2)]
    if len(b) < 30 or len(s) < 10:
        return {"not": "az_veri"}
    H, D = borsa_bul(T)
    C = H | D
    kt = pd.concat([T.groupby("kimden").kime.nunique().rename("o"), T.groupby("kime").kimden.nunique().rename("i")], axis=1).fillna(0)
    hub = set(kt[(kt.o + kt.i >= 30) & (kt.o >= 5) & (kt.i >= 5)].index) - C        # iki yonlu: havuz/router (dagiticilar haric)
    sifir = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}
    vb = b.m.sum() / 3.0
    vs = s.m.sum()
    def cexin(d):
        return d[d.kime.isin(C) & ~d.kimden.isin(C)]
    def cexout(d):
        return d[d.kimden.isin(H) & ~d.kime.isin(C)]
    ci_b, ci_s = cexin(b), cexin(s)
    yat = ci_s[~ci_s.kimden.isin(hub)].groupby("kimden").m.sum()
    aktif_b = set(b.kimden) | set(b.kime)
    yat_uyuyan = yat[~yat.index.isin(aktif_b)]
    def dagitim(d, once):
        x = d[~d.kimden.isin(C | hub | sifir) & ~d.kime.isin(C | hub | once)]
        if x.empty:
            return 0, 0.0
        g = x.groupby("kimden").agg(n=("kime", "nunique"), m=("m", "sum"))
        return int(g.n.max()), float(g.sort_values("n").m.iloc[-1])
    gor_once_s = set(T[T.t < t - pd.Timedelta(days=2)].kimden) | set(T[T.t < t - pd.Timedelta(days=2)].kime)
    dn_s, dm_s = dagitim(s, gor_once_s)
    ilk = T[T.t < t - pd.Timedelta(days=4)]
    dn_b, dm_b = dagitim(T[(T.t >= t - pd.Timedelta(days=4)) & (T.t < t - pd.Timedelta(days=2))], set(ilk.kimden) | set(ilk.kime))
    eps = 1e-12
    return {
        "n_b": len(b), "n_s": len(s), "H_say": len(H), "D_say": len(D),
        "hacim_oran": (vs / 2.0) / max(vb, eps),
        "tx_oran": (len(s) / 2.0) / max(len(b) / 3.0, eps),
        "cex_gir_oran": (ci_s.m.sum() / 2.0) / max(ci_b.m.sum() / 3.0, vb * 0.01, eps),
        "cex_gir_pay": ci_s.m.sum() / max(vs, eps),
        "cex_net_s": (ci_s.m.sum() - cexout(s).m.sum()) / max(vb, eps),
        "cex_net_b": (ci_b.m.sum() - cexout(b).m.sum()) / 3.0 / max(vb, eps),
        "yatirici_say_oran": (ci_s.kimden.nunique() / 2.0) / max(ci_b.kimden.nunique() / 3.0, 0.5),
        "en_buyuk_yatir": (yat.max() if len(yat) else 0.0) / max(vb, eps),
        "ilk5_yatir": yat.nlargest(5).sum() / max(vb, eps),
        "uyuyan_yatir": yat_uyuyan.sum() / max(vb, eps),
        "uyuyan_en_buyuk": (yat_uyuyan.max() if len(yat_uyuyan) else 0.0) / max(vb, eps),
        "dagitim_n_s": dn_s, "dagitim_n_b": dn_b, "dagitim_m_s": dm_s / max(vb, eps), "dagitim_m_b": dm_b / max(vb, eps),
    }


def main():
    z, parca, toplam = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    if z == "bsc":
        k = os.environ.get("NODEREAL_KEY", "").strip().strip('"').strip("'")
        if not k:
            print("NODEREAL_KEY yok"); return
        rpc._sira["bsc"] = [k if k.startswith("http") else f"https://bsc-mainnet.nodereal.io/v1/{k.split('/')[-1]}"]
    os.makedirs(OUTD, exist_ok=True)
    fo = f"{OUTD}/ozellik_{z}_{parca}.csv"
    W = pd.read_csv("zincir/transfer_pencereler.csv", parse_dates=["t"]); W["pid"] = W.index
    W = W[(W.zincir == z) & (W.pid % toplam == parca)]
    bitti = set(pd.read_csv(fo).pid) if os.path.exists(fo) else set()
    bas = time.time(); n = 0
    for _, w in W.iterrows():
        if w.pid in bitti:
            continue
        if time.time() - bas > SURE:
            print("sure doldu", flush=True); break
        sat = {"pid": w.pid}
        try:
            T = akilli.cek(z, w.adres, w.t - pd.Timedelta(days=5), w.t)
            sat["n"] = len(T)
            if len(T) >= akilli.MAKS_TX:
                sat["not"] = "cok_yogun"
            elif T.empty:
                sat["not"] = "transfer_yok"
            else:
                sat.update(ozellik(T, w.t))
        except Exception as exc:
            sat["not"] = "hata:" + str(exc)[:100].replace(",", ";").replace("\n", " ")
        sat.setdefault("not", "")
        kol = ["pid", "n", "not", "n_b", "n_s", "H_say", "D_say", "hacim_oran", "tx_oran", "cex_gir_oran", "cex_gir_pay",
               "cex_net_s", "cex_net_b", "yatirici_say_oran", "en_buyuk_yatir", "ilk5_yatir", "uyuyan_yatir", "uyuyan_en_buyuk",
               "dagitim_n_s", "dagitim_n_b", "dagitim_m_s", "dagitim_m_b"]
        pd.DataFrame([sat]).reindex(columns=kol).to_csv(fo, mode="a", header=not os.path.exists(fo), index=False, float_format="%.5g")
        n += 1
        print(n, w.symbol, z, w.tip, sat.get("n"), sat["not"], round((time.time() - bas) / 60), "dk", flush=True)


if __name__ == "__main__":
    main()
