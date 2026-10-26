"""
Tek coin vaka analizi (zincir ustu): pump oncesi/sonrasi cuzdan hareketleri.
Kullanim: python zincir/vaka.py SYMBOL YYYYMMDD YYYYMMDD [zincir adres]
  - Transfer kayitlari (herkese acik RPC), adres ozellikleri, borsa/havuz sezgisel etiketleri,
    dagitici kumeler, saatlik borsaya giris/cikis ve balina birikimi, fiyatla yan yana.
Cikti: arastirma_cikti/zincir/<base>_*.csv(.gz) ve <base>_ozet.txt
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from zincir import rpc
from zincir import kontrat_esle as KE

OUT = KE.OUT
SIFIR = "0x0000000000000000000000000000000000000000"


def kontrat_bul(sym):
    p = f"{OUT}/kontratlar.csv"
    if not os.path.exists(p):
        KE.main()
    k = pd.read_csv(p)
    k = k[(k.symbol == sym) & k.zincir.isin(["bsc", "eth", "base", "arb"])]
    if k.empty:
        raise SystemExit(f"{sym} icin EVM kontrati bulunamadi")
    sira = {"bsc": 0, "eth": 1, "base": 2, "arb": 3}
    r = k.sort_values("zincir", key=lambda s: s.map(sira)).iloc[0]
    return r.zincir, r.adres


def fiyat_1s(sym, t0, t1):
    fs = sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))
    for f in fs:
        d = pd.read_csv(f)
        d = d[d.symbol == sym]
        if len(d):
            birim = "s" if d.t.max() < 1e11 else "ms" if d.t.max() < 1e14 else "us"
            d["t"] = pd.to_datetime(d.t, unit=birim)
            return d[(d.t >= t0) & (d.t <= t1)].set_index("t")[["c", "v"]]
    try:
        import veri
        g = veri.mumlar("F:" + sym, "1h", t0)
        return g.set_index("open_time")[["close", "volume"]].rename(columns={"close": "c", "volume": "v"})
    except Exception as exc:
        print("fiyat yok", exc); return pd.DataFrame(columns=["c", "v"])


def main():
    sym, d0, d1 = sys.argv[1], sys.argv[2], sys.argv[3]
    base = sym.replace("USDT", "").lower()
    if len(sys.argv) > 5:
        z, adr = sys.argv[4], sys.argv[5].lower()
    elif len(sys.argv) > 4:
        k = pd.read_csv(f"{OUT}/kontratlar.csv") if os.path.exists(f"{OUT}/kontratlar.csv") else (KE.main(), pd.read_csv(f"{OUT}/kontratlar.csv"))[1]
        z = sys.argv[4]; adr = k[(k.symbol == sym) & (k.zincir == z)].adres.iloc[0]
    else:
        z, adr = kontrat_bul(sym)
    bs = z in rpc.BS or rpc.es_var(z)        # etherscan anahtari varsa bsc de bu yoldan
    os.makedirs(OUT, exist_ok=True)
    t0, t1 = pd.Timestamp(d0), pd.Timestamp(d1)
    print("coin", sym, "zincir", z, "kontrat", adr, flush=True)
    log = lambda s: print(s, flush=True)
    if bs:
        b0 = rpc.bs_zamandan_blok(z, int(t0.timestamp())); b1 = rpc.bs_zamandan_blok(z, int(t1.timestamp()))
        print("kaynak", "etherscan" if rpc.es_var(z) else "blockscout", "bloklar", b0, b1, flush=True)
        tr = rpc.bs_transferler(z, adr, b0, b1, log=log)
        T = pd.DataFrame(tr, columns=["blok", "tx", "ix", "kimden", "kime", "ham", "ts"])
    else:
        b0 = rpc.zamandan_blok(z, int(t0.timestamp())); b1 = rpc.zamandan_blok(z, int(t1.timestamp()))
        print("kaynak rpc, bloklar", b0, b1, flush=True)
        print("calisan uclar:", rpc.uclari_sec(z, adr, b1, log=log), flush=True)
        tr = rpc.transferler(z, adr, b0, b1, log=log)
        T = pd.DataFrame(tr, columns=["blok", "tx", "ix", "kimden", "kime", "ham", "ts"])
        if (T.ts == 0).any():
            T = T.drop(columns="ts")
    if T.empty:
        raise SystemExit("transfer yok")
    dec = rpc.ondalik(z, adr)
    T["miktar"] = T.ham.astype(float) / 10 ** dec
    if "ts" in T:
        T["t"] = pd.to_datetime(T.ts, unit="s"); T = T.drop(columns="ts")
    else:   # blok -> zaman (orneklenmis bloklardan ara degerleme)
        orn = np.unique(np.linspace(T.blok.min(), T.blok.max(), 60).astype(int))
        zt = np.array([rpc.blok_zaman(z, int(b)) for b in orn])
        T["t"] = pd.to_datetime(np.interp(T.blok, orn, zt), unit="s")
    T = T.drop(columns="ham").sort_values(["blok", "ix"]).reset_index(drop=True)
    T.to_csv(f"{OUT}/{base}_transferler.csv.gz", index=False, compression="gzip")
    print("transfer", len(T), "tekil adres", pd.concat([T.kimden, T.kime]).nunique(), flush=True)

    # adres ozellikleri
    gir = T.groupby("kime").agg(giris=("miktar", "sum"), gonderen=("kimden", "nunique"), ilk_giris=("t", "min"))
    cik = T.groupby("kimden").agg(cikis=("miktar", "sum"), alici=("kime", "nunique"))
    A = gir.join(cik, how="outer").fillna({"giris": 0, "cikis": 0, "gonderen": 0, "alici": 0})
    A["net"] = A.giris - A.cikis
    A["brut"] = A.giris + A.cikis
    A = A.drop(index=[SIFIR], errors="ignore")
    ust = A.sort_values("brut", ascending=False).head(80).index.tolist()
    ust += [a for a in A.sort_values("net", ascending=False).head(40).index if a not in ust]
    A["kontrat"] = pd.Series(None, index=A.index, dtype=object); A["bakiye_simdi"] = np.nan; A["isim"] = ""
    A.index.name = "adres"
    for a in ust:
        try:
            if z in rpc.BS:
                km, isim = rpc.bs_adres(z, a)
                A.loc[a, "isim"] = isim
                if km is not None:
                    A.loc[a, "kontrat"] = km
            if A.loc[a, "kontrat"] is None:
                A.loc[a, "kontrat"] = rpc.kontrat_mi(z, a)
            A.loc[a, "bakiye_simdi"] = rpc.bakiye(z, adr, a) / 10 ** dec
        except Exception as exc:
            print("adres sorgu", a, exc)
    # sezgisel etiketler
    A["etiket"] = ""
    cok = (A.gonderen >= 100) & (A.alici >= 50)
    A.loc[cok & (A.kontrat == True), "etiket"] = "havuz"          # DEX havuzu / router
    A.loc[cok & (A.kontrat != True), "etiket"] = "borsa"          # borsa sicak cuzdani (cok kaynaktan toplar, cok yere gonderir)
    BORSA_AD = ("binance", "okx", "bybit", "coinbase", "kraken", "kucoin", "gate", "bitget", "mexc", "htx", "huobi",
                "upbit", "bithumb", "crypto.com", "bitfinex", "bitstamp", "gemini", "bingx", "bitmart", "lbank")
    isimli = A.isim.str.lower().apply(lambda x: any(b in x for b in BORSA_AD))
    A.loc[isimli & (A.kontrat != True), "etiket"] = "borsa"
    borsa = set(A.index[A.etiket == "borsa"])
    # yatirma adresleri: cikisinin >=%90'i borsa cuzdanina gidenler
    kb = T[T.kime.isin(borsa)].groupby("kimden").miktar.sum()
    yat = set(kb.index[(kb / A.reindex(kb.index).cikis.replace(0, np.nan)) >= 0.9]) - borsa
    A.loc[A.index.isin(yat) & (A.etiket == ""), "etiket"] = "borsa_yatirma"
    B = borsa | yat
    # dagitici kume: ilk girisi ayni gondericiden gelen yeni adresler
    ilk = T.sort_values("t").drop_duplicates("kime")
    dag = ilk.groupby("kimden").kime.nunique()
    dag = dag[(dag >= 10) & ~dag.index.isin(B) & ~dag.index.isin(A.index[A.etiket == "havuz"])].sort_values(ascending=False)
    kume = {}
    for d, n in dag.head(20).items():
        uyeler = set(ilk.kime[ilk.kimden == d]) - B
        kume[d] = uyeler
        if A.loc[d, "etiket"] == "":
            A.loc[d, "etiket"] = "dagitici"
        A.loc[A.index.isin(uyeler) & (A.etiket == ""), "etiket"] = "kume:" + d[:8]
    A.sort_values("brut", ascending=False).to_csv(f"{OUT}/{base}_adresler.csv")

    # balinalar: etiketsiz/kume EOA'lar icinde en buyuk net birikim
    aday = A[(A.etiket.isin(["", "dagitici"]) | A.etiket.str.startswith("kume")) & (A.kontrat != True)]
    balina = set(aday.sort_values("net", ascending=False).head(30).index)
    # saatlik seriler
    T["saat"] = T.t.dt.floor("h")
    havuz = set(A.index[A.etiket == "havuz"])
    S = pd.DataFrame({
        "transfer": T.groupby("saat").size(),
        "borsaya_giris": T[T.kime.isin(B) & ~T.kimden.isin(B)].groupby("saat").miktar.sum(),
        "borsadan_cikis": T[T.kimden.isin(borsa) & ~T.kime.isin(B)].groupby("saat").miktar.sum(),
        "havuzdan_alim": T[T.kimden.isin(havuz) & ~T.kime.isin(havuz)].groupby("saat").miktar.sum(),
        "havuza_satis": T[T.kime.isin(havuz) & ~T.kimden.isin(havuz)].groupby("saat").miktar.sum(),
        "balina_net": T[T.kime.isin(balina)].groupby("saat").miktar.sum().sub(
            T[T.kimden.isin(balina)].groupby("saat").miktar.sum(), fill_value=0),
        "kume_net": T[T.kime.isin(set().union(*kume.values()) if kume else set())].groupby("saat").miktar.sum(),
        "yeni_adres": ilk.assign(saat=ilk.t.dt.floor("h")).groupby("saat").size(),
    }).fillna(0).sort_index()
    S["borsa_net_giris"] = S.borsaya_giris - S.borsadan_cikis
    S["balina_kum"] = S.balina_net.cumsum()
    F = fiyat_1s(sym, t0, t1)
    S = S.join(F.rename(columns={"c": "fiyat", "v": "vadeli_hacim"}), how="outer").sort_index()
    S.to_csv(f"{OUT}/{base}_saatlik.csv")

    # gunluk ozet
    G = S.resample("1D").agg({"fiyat": "last", "transfer": "sum", "yeni_adres": "sum", "borsaya_giris": "sum",
                              "borsadan_cikis": "sum", "borsa_net_giris": "sum", "balina_net": "sum", "kume_net": "sum",
                              "havuzdan_alim": "sum", "havuza_satis": "sum"})
    with open(f"{OUT}/{base}_ozet.txt", "w") as f:
        p = lambda *a: (print(*a, flush=True), print(*a, file=f))
        p(f"{sym} zincir={z} kontrat={adr} {d0}-{d1} transfer={len(T)} adres={len(A)}")
        p("etiketler:", A.etiket.replace("", "-").str.split(":").str[0].value_counts().to_dict())
        p("borsa cuzdanlari:", len(borsa), "yatirma adresleri:", len(yat), "dagitici kume:", len(kume),
          {k[:10]: len(v) for k, v in list(kume.items())[:8]})
        if z in rpc.BS:
            try:
                H = pd.DataFrame(rpc.bs_holderlar(z, adr))
                arz = int(rpc.cagir_arz(z, adr)) / 10 ** dec if hasattr(rpc, "cagir_arz") else None
                H["miktar"] = H.deger.astype(float) / 10 ** dec
                H["kume"] = H.adres.map(A.etiket).fillna("")
                H.to_csv(f"{OUT}/{base}_holderlar.csv", index=False)
                top = H.miktar.sum()
                p(f"\nEN BUYUK {len(H)} HOLDER toplam {top:,.0f} token; ilk 10 payi (bu listede): {H.miktar.head(10).sum() / top:.1%}")
                p(H.head(15)[["adres", "miktar", "kontrat", "isim", "kume"]].to_string())
            except Exception as exc:
                p("holder listesi alinamadi", exc)
        p("\nGUNLUK (miktarlar token):")
        p(G.round(0).to_string())
        p("\nEN BUYUK NET BIRIKIM (EOA, borsa/havuz disi):")
        p(aday.sort_values("net", ascending=False).head(15)[["net", "giris", "cikis", "gonderen", "ilk_giris", "bakiye_simdi", "etiket", "isim"]].round({"net": 0, "giris": 0, "cikis": 0, "bakiye_simdi": 0}).to_string())
        p("\nEN BUYUK NET CIKIS (satanlar):")
        p(aday.sort_values("net").head(15)[["net", "giris", "cikis", "alici", "bakiye_simdi", "etiket", "isim"]].round(0).to_string())


if __name__ == "__main__":
    main()
