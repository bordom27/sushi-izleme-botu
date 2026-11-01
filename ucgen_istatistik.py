"""
Daralan ucgen sinyallerinin gecmis isabeti (ucgen_tarayici.py ile ayni tespit kodu).

Olculenler (her kirilim icin, kirilimdan sonraki en fazla 100 mum):
  hedef      : gecersizlik seviyesine (karsi cizgi) dokunmadan olculen hedefe ulasti mi
  yarim      : ayni, hedefin yarisi icin
  sahte      : kirilimdan sonraki 3 mum icinde kapanis ucgenin icine geri dondu mu
  R (tam/yarim): kirilim mumunun kapanisindan girip stop = gecersizlik, kar al = hedef (veya yarim hedef)
               ile islem yapilsaydi riske edilen 1 birim basina ortalama sonuc. 100 mumda ikisi de
               olmazsa son kapanistan cikilir; bosluklu acilista acilis fiyatindan cikilir.
  RR         : giriste odul/risk orani (medyan, tam hedef icin)
'Kirilima yakin' sinyali: ayni ucgen sonradan sinyal verilen yonde mi kirildi.
Ayni bar icinde hem hedef hem gecersizlik gorulurse basarisiz sayilir (temkinli).

Hisselerde 4 saatlik mumlar Yahoo'nun 1 saatlik verisinden (son ~2 yil) seans icinde 4'erli
bloklar halinde kurulur (TradingView 4s ile ayni hiza: ABD 09:30/13:30, BIST 10:00/14:00).
'-son-donem' gruplari gunluk veriyi 4 saatlik verinin kapsadigi doneme kirpar (adil karsilastirma).

Kullanim: ARALIKLAR=4h,1d,3d,1w python ucgen_istatistik.py   (GitHub Actions'ta sonuclar not olarak yazilir)
3 gunluk (3d) ve haftalik (1w): kripto Binance'in kendi mumlari; hisselerde haftalik Yahoo, 3 gunluk ise
gunluk verinin 3'er islem gunluk bloklari (son 20 yil).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import ucgen_tarayici as u

ARALIK_MS = {"4h": 4 * 3600_000, "1d": 86400_000, "3d": 3 * 86400_000, "1w": 7 * 86400_000, "1dL": 86400_000}
BAR = {"4h": 2000, "1d": 1000, "3d": 1300, "1w": 700, "1dL": 4000}   # kripto: 4s ~ 333 gun, 1g ~ 2,7 yil
MIN_VERI = {"4h": 300, "1d": 300, "3d": 120, "1w": 120, "1dL": 300}  # bundan kisa gecmisli grafik alinmaz
BINANCE_AD = {"1dL": "1d"}               # 1dL: uzun gecmisli gunluk (hisse 20 yil, kripto tum gecmis)
YAHOO_YIL = 20                           # hisselerde 3 gunluk / haftalik icin gecmis (yil)
R_TAVAN = 5.0                            # ortalamada tek islemin katkisi en fazla +5R (tepe noktasina yakin
                                         # kirilimlarda stop cok dar olur, ortalamayi sisirmesin)


def binance_uzun(sym: str, aralik: str) -> dict | None:
    simdi = int(time.time() * 1000)
    bas = simdi - BAR[aralik] * ARALIK_MS[aralik]
    satir = []
    while bas < simdi:
        v = u._get("https://data-api.binance.vision/api/v3/klines",
                   dict(symbol=sym, interval=BINANCE_AD.get(aralik, aralik), startTime=bas, limit=1000))
        if not v:
            break
        satir += v
        if len(v) < 1000:
            break
        bas = v[-1][0] + ARALIK_MS[aralik]
    satir = [k for k in satir if k[6] < simdi]
    if len(satir) < MIN_VERI[aralik] or simdi - satir[-1][6] > 2 * ARALIK_MS[aralik]:
        return None
    a = np.array([[k[0] / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])] for k in satir])
    kap = a[-120:, 4]
    if kap.std() / kap.mean() < 0.01:
        return None
    return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])


def yahoo_uzun(sym: str, aralik: str = "1d") -> dict | None:
    """Gunluk: son 5 yil. Haftalik: son 20 yil (bitmemis son hafta atilir).
    3 gunluk: son 20 yilin gunlugu 3'er islem gunluk bloklara birlestirilir (bitmemis son blok atilir)."""
    simdi = int(time.time())
    if aralik == "1d":
        parametre = dict(range="5y", interval="1d")
    else:
        parametre = dict(period1=simdi - YAHOO_YIL * 365 * 86400, period2=simdi,
                         interval="1wk" if aralik == "1w" else "1d")
    yas = {"1d": 8, "1dL": 8, "3d": 12, "1w": 21}[aralik]  # son mumun en fazla kac gunluk olabilecegi
    for host in ("query1", "query2"):
        j = u._get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", parametre, deneme=2)
        if not j:
            continue
        try:
            x = j["chart"]["result"][0]
            q = x["indicators"]["quote"][0]
            bugun = int(time.time() // 86400)
            sat = [(t, o, h, l, c, v or 0) for t, o, h, l, c, v in
                   zip(x["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
                   if None not in (o, h, l, c) and t // 86400 < bugun]
            if aralik == "1w":
                sat = sat[:-1]                                  # bu haftanin mumu henuz bitmedi
            elif aralik == "3d":
                sat = [(sat[i][0], sat[i][1], max(r[2] for r in sat[i:i + 3]), min(r[3] for r in sat[i:i + 3]),
                        sat[i + 2][4], sum(r[5] for r in sat[i:i + 3])) for i in range(0, len(sat) - 2, 3)]
            if len(sat) < MIN_VERI[aralik] or time.time() - sat[-1][0] > yas * 86400:
                return None
            a = np.array(sat, dtype=float)
            return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])
        except Exception:  # noqa: BLE001
            continue
    return None


def yahoo_4s(sym: str) -> dict | None:
    """Yahoo 1 saatlik veriyi (son ~2 yil) her seans icinde 4'erli bloklara birlestirir."""
    simdi = int(time.time())
    for host in ("query1", "query2"):
        j = u._get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                   dict(period1=simdi - 729 * 86400, period2=simdi, interval="1h"), deneme=2)
        if not j:
            continue
        try:
            x = j["chart"]["result"][0]
            q = x["indicators"]["quote"][0]
            ofs = int(x["meta"].get("gmtoffset") or 0)
            bugun = (simdi + ofs) // 86400
            blok: list = []          # [gun, blok_no, t, o, h, l, c, v]
            gun0, sira = None, 0
            for t, o, h, l, c, v in zip(x["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]):
                if None in (o, h, l, c):
                    continue
                gun = (t + ofs) // 86400
                if gun >= bugun:
                    continue
                if gun != gun0:
                    gun0, sira = gun, 0
                no = sira // 4
                sira += 1
                if blok and blok[-1][0] == gun and blok[-1][1] == no:
                    B = blok[-1]
                    B[4], B[5], B[6], B[7] = max(B[4], h), min(B[5], l), c, B[7] + (v or 0)
                else:
                    blok.append([gun, no, t, o, h, l, c, v or 0])
            if len(blok) < 300 or simdi - blok[-1][2] > 8 * 86400:
                return None
            a = np.array([B[2:] for B in blok], dtype=float)
            return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])
        except Exception:  # noqa: BLE001
            continue
    return None


def _yukseklik(o: dict) -> float:
    return o["f"]["w0"] if o["desen"] == "ucgen" else o["f"]["yuk"]


def _kirilan_cizgi(o: dict, i: int) -> float:
    """Sahte kirilim denetimi: ucgende kirilan cizgi, donus formasyonunda boyun cizgisi."""
    if o["desen"] == "ucgen":
        return u.deger(o["f"], i, "u" if o["yon"] == "yukari" else "l")
    return u.boyun(o["f"], i)


def kirilim_sonucu(d: dict, o: dict):
    N = len(d["c"])
    f, b, yukari = o["f"], o["b"], o["yon"] == "yukari"
    yarim = o["seviye"] + (0.5 if yukari else -0.5) * _yukseklik(o)
    hedef_ok = yarim_ok = None
    sahte = False
    for i in range(b + 1, min(N, b + 101)):
        if i <= b + 3:
            if (yukari and d["c"][i] < _kirilan_cizgi(o, i)) or (not yukari and d["c"][i] > _kirilan_cizgi(o, i)):
                sahte = True
        bozuldu = d["l"][i] <= o["gecersiz"] if yukari else d["h"][i] >= o["gecersiz"]
        if bozuldu:
            hedef_ok = False if hedef_ok is None else hedef_ok
            yarim_ok = False if yarim_ok is None else yarim_ok
            break
        uc = d["h"][i] if yukari else d["l"][i]
        if yarim_ok is None and ((yukari and uc >= yarim) or (not yukari and uc <= yarim)):
            yarim_ok = True
        if hedef_ok is None and ((yukari and uc >= o["hedef"]) or (not yukari and uc <= o["hedef"])):
            hedef_ok = True
            break
    return hedef_ok, yarim_ok, sahte, islem_r(d, o, 1.0), islem_r(d, o, 0.5), rr_oran(d, o)


def islem_r(d: dict, o: dict, kat: float):
    """Kirilim kapanisindan giris; stop = gecersizlik, kar al = seviye +/- kat*yukseklik. Sonuc R cinsinden."""
    N, b = len(d["c"]), o["b"]
    s = 1 if o["yon"] == "yukari" else -1
    giris = d["c"][b]
    tp = o["seviye"] + s * kat * _yukseklik(o)
    risk, odul = s * (giris - o["gecersiz"]), s * (tp - giris)
    if risk <= 0 or odul <= 0:        # kar al seviyesi giriste zaten gecilmis: islem yok
        return None
    son = min(N - 1, b + 100)
    for i in range(b + 1, son + 1):
        acilis = d["o"][i]
        aleyhe = d["l"][i] if s == 1 else d["h"][i]
        lehe = d["h"][i] if s == 1 else d["l"][i]
        if s * (acilis - o["gecersiz"]) <= 0:      # stopun otesinde acildi
            return s * (acilis - giris) / risk
        if s * (aleyhe - o["gecersiz"]) <= 0:
            return -1.0
        if s * (acilis - tp) >= 0:                 # hedefin otesinde acildi
            return s * (acilis - giris) / risk
        if s * (lehe - tp) >= 0:
            return odul / risk
    return s * (d["c"][son] - giris) / risk


def rr_oran(d: dict, o: dict):
    s = 1 if o["yon"] == "yukari" else -1
    giris = d["c"][o["b"]]
    risk, odul = s * (giris - o["gecersiz"]), s * (o["hedef"] - giris)
    return odul / risk if risk > 0 and odul > 0 else None


def yuzde(a: list) -> str:
    a = [x for x in a if x is not None]
    return f"%{100 * sum(a) / len(a):.0f}" if a else "-"


def ort_r(a: list) -> str:
    a = [min(x, R_TAVAN) for x in a if x is not None]
    return f"{np.mean(a):+.2f}R" if a else "-"


def medyan(a: list) -> str:
    a = [x for x in a if x is not None]
    return f"{np.median(a):.1f}" if a else "-"


def ozet(k: list) -> str:
    return (f"n={len(k)} hedef {yuzde([x[0] for x in k])} yarim {yuzde([x[1] for x in k])} "
            f"sahte {yuzde([x[2] for x in k])} Rtam {ort_r([x[3] for x in k])} "
            f"Ryarim {ort_r([x[4] for x in k])} RR {medyan([x[5] for x in k])}")


def main():
    isler = []
    kripto = u.kripto_listesi()
    bist, abd = list(dict.fromkeys(u.BIST)), list(u.ABD)
    araliklar = [a.strip() for a in (os.environ.get("ARALIKLAR") or "4h,1d").split(",") if a.strip() in ARALIK_MS]
    for a in araliklar:
        isler += [("KRIPTO", s, a) for s in kripto] + [("BIST", s, a) for s in bist] + [("ABD", s, a) for s in abd]

    def al(is_):
        p, s, a = is_
        if p == "KRIPTO":
            return binance_uzun(s, a)
        ys = s + ".IS" if p == "BIST" else s
        return yahoo_4s(ys) if a == "4h" else yahoo_uzun(ys, a)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(al, isler))
    # her piyasada 4 saatlik verinin basladigi tarih: gunlugu ayni doneme de kirpmak icin
    bas4: dict = {}
    for (p, s, a), d in zip(isler, veriler):
        if d is not None and a == "4h":
            bas4[p] = min(bas4.get(p, d["t"][0]), d["t"][0])

    gruplar: dict = {}
    for (p, s, a), d in zip(isler, veriler):
        if d is None:
            continue
        _, olaylar = u.tara(d)
        N = len(d["c"])
        sonu = {}                                   # formasyon -> kirilim yonu / 'bitti'
        for o in olaylar:
            if o["tur"] in ("kirilim", "bitti"):
                sonu[(o["desen"], o["f"]["key"])] = o["yon"] if o["tur"] == "kirilim" else "bitti"
        for o in olaylar:
            if o["tur"] == "bitti" or o["b"] > N - 30:
                continue
            if o["desen"] == "ucgen":
                hedefler = [(f"{p}-{a}", None)]
                if a == "1d" and p in bas4:
                    hedefler.append((f"{p}-{a}-son-donem", bas4[p]))
            else:
                hedefler = [(f"{o['desen']}-{a}", None)]
            for ad, bas in hedefler:
                if bas is not None and d["t"][o["b"]] < bas:
                    continue
                g = gruplar.setdefault(ad, dict(grafik=set(), kir={"yukari": [], "asagi": []}, yakin=[]))
                g["grafik"].add((p, s, a))
                if o["tur"] == "kirilim":
                    g["kir"][o["yon"]].append(kirilim_sonucu(d, o))
                else:
                    sonuc = sonu.get((o["desen"], o["f"]["key"]))
                    if o["desen"] == "ucgen":     # yakin uyarisinin yonu dogru mu (kirilan ucgenler arasinda)
                        beklenen = "yukari" if o["yon"] == "ust" else "asagi"
                        g["yakin"].append(None if sonuc in (None, "bitti") else sonuc == beklenen)
                    else:                         # boyun yakini sonrasi formasyon onaylandi mi (bozulana karsi)
                        g["yakin"].append(None if sonuc is None else sonuc != "bitti")

    satirlar = [f"sure {time.time() - t0:.0f} sn"]
    for ad in sorted(gruplar):
        g = gruplar[ad]
        parca = [f"{ad} ({len(g['grafik'])} grafik): KIRILIM {ozet(g['kir']['yukari'] + g['kir']['asagi'])}"]
        for yon in ("yukari", "asagi"):
            if g["kir"][yon]:
                parca.append(f"{yon} {ozet(g['kir'][yon])}")
        y = g["yakin"]
        cozulen = [x for x in y if x is not None]
        parca.append(f"YAKIN n={len(y)} sonuclanan {len(cozulen)} {'dogru-yon' if '-' in ad and ad.split('-')[0] in ('KRIPTO', 'BIST', 'ABD') else 'onaylanan'} {yuzde(cozulen)}")
        satirlar.append(" | ".join(parca))
    for s in satirlar:
        print(s)
    if os.environ.get("GITHUB_ACTIONS") == "true":          # not basina sinir var: 4'erli parcalar
        for i in range(0, len(satirlar), 4):
            print("::notice::" + " %0A ".join(x.replace("%", "%25") for x in satirlar[i:i + 4]))


if __name__ == "__main__":
    main()
