"""
Sistematik test: pump oncesi 8 gunluk zincir ustu aktivite (Etherscan, eth) - pump olaylari vs ayni coinin kontrol donemleri.
Girdi: zincir/olaylar.csv (symbol, t = pump oncesi son 4s mumun kapanisi, tip olay/kontrol, adres)
Cikti: arastirma_cikti/zincir/olay_ozellik.csv (kaldigi yerden devam eder)
Ozellikler (son 48s, onceki 6 gunluk tabana gore, gunluk oranlar):
  tx_oran, adres_oran, yeni_adres_oran, buyuk_tx_oran (taban %99 ustu), hub_net_cikis (borsa/havuz benzeri dugumlerden net cikis / taban gunluk hacim),
  alim_yogunluk (son 48s'te en buyuk 10 alicinin net alim payi)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from zincir import rpc

OUT = "arastirma_cikti/zincir/olay_ozellik.csv"
SURE = float(os.environ.get("MAKS_DAKIKA", "300")) * 60
MAKS_TX = 150_000            # cok yogun tokenlarda pencereyi atla (API butcesi)


def ozellik(T, t_son):
    T = T.copy()
    T["t"] = pd.to_datetime(T.ts, unit="s")
    pre0 = t_son - pd.Timedelta(hours=48)
    base = T[T.t < pre0]; pre = T[T.t >= pre0]
    if len(base) < 30:
        return None
    gun_b, gun_p = 6.0, 2.0
    # 2 gunluk dilimler: tabanda 3 dilim (k=0,1,2), son 48s dilim 3 -> esit uzunlukta karsilastirma
    dil = [T[(T.t >= t_son - pd.Timedelta(days=8 - 2 * k)) & (T.t < t_son - pd.Timedelta(days=6 - 2 * k))] for k in range(4)]
    adr_s = [set(d.kimden) | set(d.kime) for d in dil]
    yeni = [len(adr_s[k] - adr_s[k - 1]) for k in (1, 2, 3)]
    esik = base.miktar.quantile(0.99)
    # hub: tabanda cok sayida farkli karsi taraf (borsa/havuz)
    kt = pd.concat([base.groupby("kimden").kime.nunique(), base.groupby("kime").kimden.nunique()], axis=1).fillna(0).sum(axis=1)
    hub = set(kt[kt >= 30].index)
    hacim_b = base.miktar.sum() / gun_b
    def hubnet(d):
        cik = d[d.kimden.isin(hub) & ~d.kime.isin(hub)].miktar.sum()
        gir = d[d.kime.isin(hub) & ~d.kimden.isin(hub)].miktar.sum()
        return cik - gir
    alim = pre.groupby("kime").miktar.sum().sub(pre.groupby("kimden").miktar.sum(), fill_value=0)
    alim = alim[~alim.index.isin(hub)]
    return {
        "n_taban": len(base), "n_son": len(pre),
        "tx_oran": (len(pre) / gun_p) / (len(base) / gun_b),
        "adres_oran": len(adr_s[3]) / max(1, np.mean([len(x) for x in adr_s[:3]])),
        "yeni_adres_oran": yeni[2] / max(1, np.mean(yeni[:2])),
        "buyuk_tx_oran": ((pre.miktar >= esik).sum() / gun_p) / max(0.5, (base.miktar >= esik).sum() / gun_b),
        "hub_net_cikis_son": hubnet(pre) / gun_p / max(hacim_b, 1e-9),
        "hub_net_cikis_taban": hubnet(base) / gun_b / max(hacim_b, 1e-9),
        "alim_yogunluk": alim[alim > 0].nlargest(10).sum() / max(pre.miktar.sum(), 1e-9),
        "hacim_oran": (pre.miktar.sum() / gun_p) / max(hacim_b, 1e-9),
        "hub_say": len(hub),
    }


def main():
    O = pd.read_csv("zincir/olaylar.csv", parse_dates=["t"])
    bitti = set()
    if os.path.exists(OUT):
        d = pd.read_csv(OUT, parse_dates=["t"])
        bitti = set(zip(d.symbol, d.t.astype(str)))
    bas = time.time(); n = 0
    for _, r in O.iterrows():
        if (r.symbol, str(r.t)) in bitti:
            continue
        if time.time() - bas > SURE:
            print("sure doldu", flush=True); break
        t_son = r.t; t_bas = t_son - pd.Timedelta(days=8)
        satir = {"symbol": r.symbol, "t": r.t, "tip": r.tip, "r42": r.r42, "vx18": r.vx18, "ileri": r.ileri}
        try:
            b0 = rpc.bs_zamandan_blok("eth", int(t_bas.timestamp())); b1 = rpc.bs_zamandan_blok("eth", int(t_son.timestamp()))
            tr = rpc.bs_transferler("eth", r.adres, b0, b1, log=lambda s: None, maks=MAKS_TX)
            T = pd.DataFrame(tr, columns=["blok", "tx", "ix", "kimden", "kime", "ham", "ts"])
            if len(T) >= MAKS_TX:
                satir["not"] = "cok_yogun"
            elif T.empty:
                satir["not"] = "transfer_yok"
            else:
                T["miktar"] = T.ham.astype(float)
                f = ozellik(T, t_son)
                satir.update(f or {"not": "taban_az"})
        except Exception as exc:
            satir["not"] = "hata:" + str(exc)[:80]
        n += 1
        pd.DataFrame([satir]).to_csv(OUT, mode="a", header=not os.path.exists(OUT), index=False)
        print(n, r.symbol, r.tip, satir.get("tx_oran"), satir.get("not", ""), flush=True)


if __name__ == "__main__":
    main()
