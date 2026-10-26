"""
Akilli para arastirmasi - adim 1 (GitHub Actions): her pencere icin cuzdan ozetleri.
  olay penceresi:   [t-7g, t+3g]  (t = pump oncesi son 4s mum kapanisi; pump t..t+24s icinde)
  kontrol penceresi: [t-7g, t]
Her pencerede borsa/havuz benzeri dugumler (>=30 farkli karsi taraf) ayrilir; diger adresler icin:
  on = t oncesi 7 gun net alim, on48 = son 48s net alim, sonra = t sonrasi 3 gun net (negatif = satis)
  hepsi pencerenin on-donem token hacmine oranla.
Kullanim: python zincir/akilli.py <zincir> <parca> <toplam>
Cikti: arastirma_cikti/zincir/akilli/cuzdan_<zincir>_<parca>.csv, pencere_<zincir>_<parca>.csv  (kaldigi yerden devam)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from zincir import rpc

OUTD = "arastirma_cikti/zincir/akilli"
SURE = float(os.environ.get("MAKS_DAKIKA", "320")) * 60
MAKS_TX = 120_000
UST = 150


def cek(z, adr, t0, t1):
    if z == "eth":
        b0 = rpc.bs_zamandan_blok("eth", int(t0.timestamp())); b1 = rpc.bs_zamandan_blok("eth", int(t1.timestamp()))
        tr = rpc.bs_transferler("eth", adr, b0, b1, log=lambda s: None, maks=MAKS_TX)
        T = pd.DataFrame(tr, columns=["blok", "tx", "ix", "kimden", "kime", "ham", "ts"])
    else:
        b0 = rpc.tahmini_blok(z, int(t0.timestamp())); b1 = rpc.tahmini_blok(z, int(t1.timestamp()))
        tr = rpc.transferler(z, adr, b0, b1, adim=5000, tavan=50000, log=lambda s: None, maks=MAKS_TX)
        T = pd.DataFrame(tr, columns=["blok", "tx", "ix", "kimden", "kime", "ham", "ts"])
        if len(T) and (T.ts == 0).any():
            orn = np.unique(np.r_[b0, b1, np.linspace(T.blok.min(), T.blok.max(), 10).astype(int)])
            zt = np.array([rpc.blok_zaman(z, int(b)) for b in orn])
            T["ts"] = np.interp(T.blok, orn, zt)
    return T


def ozet(T, t, olay):
    T = T[T.kimden != T.kime].copy()
    T["m"] = T.ham.astype(float)
    T["t"] = pd.to_datetime(T.ts, unit="s")
    kt = pd.concat([T.groupby("kimden").kime.nunique(), T.groupby("kime").kimden.nunique()], axis=1).fillna(0).sum(axis=1)
    hub = set(kt[kt >= 30].index) | {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}
    on = T[T.t < t]; on48 = on[on.t >= t - pd.Timedelta(hours=48)]; son = T[T.t >= t]
    V = on.m.sum()
    if len(on) < 20 or V <= 0:
        return None, {"not": "az_veri"}
    def net(d):
        x = d.groupby("kime").m.sum().sub(d.groupby("kimden").m.sum(), fill_value=0)
        return x[~x.index.isin(hub)] / V
    a, b, c = net(on), net(on48), net(son) if olay else pd.Series(dtype=float)
    secim = set(a[a > 0].nlargest(UST).index) | set(b[b > 0].nlargest(100).index)
    R = pd.DataFrame({"on": a.reindex(list(secim)), "on48": b.reindex(list(secim)), "sonra": c.reindex(list(secim))}).fillna(0)
    R.index.name = "adres"
    return R, {"n_on": len(on), "n_son": len(son), "hub_say": len(hub), "adres_say": kt.size}


def main():
    z, parca, toplam = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    if z == "bsc":
        if not os.environ.get("NODEREAL_KEY"):
            print("NODEREAL_KEY yok, bsc atlandi"); return
        k = os.environ["NODEREAL_KEY"].strip().strip('"').strip("'")
        url = k if k.startswith("http") else f"https://bsc-mainnet.nodereal.io/v1/{k.split('/')[-1]}"
        print("anahtar uzunlugu", len(k), "| tam adres mi:", k.startswith("http"), "| bicim:", url.split("/v1/")[0], flush=True)
        import requests
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=30)
        print("deneme:", r.status_code, r.text[:300].replace(k, "***"), flush=True)
        rpc._sira["bsc"] = [url]
    os.makedirs(OUTD, exist_ok=True)
    fc, fp = f"{OUTD}/cuzdan_{z}_{parca}.csv", f"{OUTD}/pencere_{z}_{parca}.csv"
    W = pd.read_csv("zincir/akilli_pencereler.csv", parse_dates=["t"])
    W["pid"] = W.index
    W = W[(W.zincir == z) & (W.pid % toplam == parca)]
    bitti = set(pd.read_csv(fp).pid) if os.path.exists(fp) else set()
    bas = time.time(); n = 0
    for _, w in W.iterrows():
        if w.pid in bitti:
            continue
        if time.time() - bas > SURE:
            print("sure doldu", flush=True); break
        olay = w.tip == "olay"
        t = w.t
        bilgi = {"pid": w.pid}
        try:
            T = cek(z, w.adres, t - pd.Timedelta(days=7), t + pd.Timedelta(days=3) if olay else t)
            bilgi["n"] = len(T)
            if len(T) >= MAKS_TX:
                bilgi["not"] = "cok_yogun"
            elif T.empty:
                bilgi["not"] = "transfer_yok"
            else:
                R, ek = ozet(T, t, olay)
                bilgi.update(ek)
                if R is not None and len(R):
                    R = R.reset_index(); R.insert(0, "pid", w.pid)
                    R.to_csv(fc, mode="a", header=not os.path.exists(fc), index=False, float_format="%.5g")
        except Exception as exc:
            bilgi["not"] = "hata:" + str(exc)[:100].replace(",", ";").replace("\n", " ")
        bilgi.setdefault("not", "")
        pd.DataFrame([bilgi])[["pid", "n", "not"] if "n" in bilgi else ["pid", "not"]].reindex(columns=["pid", "n", "not"]).to_csv(
            fp, mode="a", header=not os.path.exists(fp), index=False)
        n += 1
        print(n, w.symbol, z, w.tip, bilgi.get("n"), bilgi["not"], round((time.time() - bas) / 60), "dk", flush=True)


if __name__ == "__main__":
    main()
