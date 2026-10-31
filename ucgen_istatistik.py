"""
Daralan ucgen sinyallerinin gecmis isabeti (ucgen_tarayici.py ile ayni tespit kodu).

Olculenler (her kirilim icin, kirilimdan sonraki en fazla 100 mum):
  hedef      : gecersizlik seviyesine (karsi cizgi) dokunmadan olculen hedefe ulasti mi
  yarim      : ayni, hedefin yarisi icin
  sahte      : kirilimdan sonraki 3 mum icinde kapanis ucgenin icine geri dondu mu
'Kirilima yakin' sinyali: ayni ucgen sonradan sinyal verilen yonde mi kirildi.
Ayni bar icinde hem hedef hem gecersizlik gorulurse basarisiz sayilir (temkinli).

Kullanim: python ucgen_istatistik.py   (GitHub Actions'ta sonuclar not olarak yazilir)
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import ucgen_tarayici as u

ARALIK_MS = {"4h": 4 * 3600_000, "1d": 86400_000}
BAR = {"4h": 2000, "1d": 1000}           # 4s ~ 333 gun, 1g ~ 2,7 yil


def binance_uzun(sym: str, aralik: str) -> dict | None:
    simdi = int(time.time() * 1000)
    bas = simdi - BAR[aralik] * ARALIK_MS[aralik]
    satir = []
    while bas < simdi:
        v = u._get("https://data-api.binance.vision/api/v3/klines",
                   dict(symbol=sym, interval=aralik, startTime=bas, limit=1000))
        if not v:
            break
        satir += v
        if len(v) < 1000:
            break
        bas = v[-1][0] + ARALIK_MS[aralik]
    satir = [k for k in satir if k[6] < simdi]
    if len(satir) < 300 or simdi - satir[-1][6] > 2 * ARALIK_MS[aralik]:
        return None
    a = np.array([[k[0] / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])] for k in satir])
    kap = a[-120:, 4]
    if kap.std() / kap.mean() < 0.01:
        return None
    return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])


def yahoo_uzun(sym: str) -> dict | None:
    for host in ("query1", "query2"):
        j = u._get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", dict(range="5y", interval="1d"), deneme=2)
        if not j:
            continue
        try:
            x = j["chart"]["result"][0]
            q = x["indicators"]["quote"][0]
            bugun = int(time.time() // 86400)
            sat = [(t, o, h, l, c, v or 0) for t, o, h, l, c, v in
                   zip(x["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
                   if None not in (o, h, l, c) and t // 86400 < bugun]
            if len(sat) < 300 or time.time() - sat[-1][0] > 8 * 86400:
                return None
            a = np.array(sat, dtype=float)
            return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])
        except Exception:  # noqa: BLE001
            continue
    return None


def kirilim_sonucu(d: dict, o: dict):
    N = len(d["c"])
    f, b, yukari = o["f"], o["b"], o["yon"] == "yukari"
    yarim = o["seviye"] + (0.5 if yukari else -0.5) * f["w0"]
    hedef_ok = yarim_ok = None
    sahte = False
    for i in range(b + 1, min(N, b + 101)):
        if i <= b + 3:
            if (yukari and d["c"][i] < u.deger(f, i, "u")) or (not yukari and d["c"][i] > u.deger(f, i, "l")):
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
    return hedef_ok, yarim_ok, sahte


def yuzde(a: list) -> str:
    a = [x for x in a if x is not None]
    return f"%{100 * sum(a) / len(a):.0f}" if a else "-"


def main():
    isler = []
    kripto = u.kripto_listesi()
    isler += [("KRIPTO", s, "4h") for s in kripto] + [("KRIPTO", s, "1d") for s in kripto]
    isler += [("BIST", s, "1d") for s in dict.fromkeys(u.BIST)] + [("ABD", s, "1d") for s in u.ABD]

    def al(is_):
        p, s, a = is_
        return binance_uzun(s, a) if p == "KRIPTO" else yahoo_uzun(s + ".IS" if p == "BIST" else s)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(al, isler))
    # 4 saatlik verinin basladigi tarih: gunluk kriptoyu ayni doneme de kirpmak icin
    bas4 = min((d["t"][0] for (p, s, a), d in zip(isler, veriler) if d is not None and a == "4h"), default=0)

    gruplar: dict = {}
    for (p, s, a), d in zip(isler, veriler):
        if d is None:
            continue
        _, olaylar = u.tara(d)
        N = len(d["c"])
        anahtarlar = {}
        for o in olaylar:
            if o["tur"] == "kirilim":
                anahtarlar[o["f"]["key"]] = o["yon"]
        hedefler = [(f"{p}-{a}", None)]
        if p == "KRIPTO" and a == "1d":
            hedefler.append((f"{p}-{a}-son-donem", bas4))
        for ad, bas in hedefler:
            g = gruplar.setdefault(ad, dict(grafik=0, kir={"yukari": [], "asagi": []}, yakin=[]))
            g["grafik"] += 1
            for o in olaylar:
                if o["b"] > N - 30 or (bas is not None and d["t"][o["b"]] < bas):
                    continue
                if o["tur"] == "kirilim":
                    g["kir"][o["yon"]].append(kirilim_sonucu(d, o))
                else:
                    sonuc = anahtarlar.get(o["f"]["key"])
                    beklenen = "yukari" if o["yon"] == "ust" else "asagi"
                    g["yakin"].append(None if sonuc is None else sonuc == beklenen)

    satirlar = [f"sure {time.time() - t0:.0f} sn"]
    for ad in sorted(gruplar):
        g = gruplar[ad]
        tum = g["kir"]["yukari"] + g["kir"]["asagi"]
        parca = [f"{ad} ({g['grafik']} grafik): KIRILIM n={len(tum)} hedef {yuzde([x[0] for x in tum])} "
                 f"yarim {yuzde([x[1] for x in tum])} sahte {yuzde([x[2] for x in tum])}"]
        for yon in ("yukari", "asagi"):
            k = g["kir"][yon]
            parca.append(f"{yon} n={len(k)} hedef {yuzde([x[0] for x in k])} yarim {yuzde([x[1] for x in k])} "
                         f"sahte {yuzde([x[2] for x in k])}")
        y = g["yakin"]
        cozulen = [x for x in y if x is not None]
        parca.append(f"YAKIN n={len(y)} kirilan {len(cozulen)} dogru-yon {yuzde(cozulen)}")
        satirlar.append(" | ".join(parca))
    for s in satirlar:
        print(s)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::notice::" + " %0A ".join(x.replace("%", "%25") for x in satirlar))


if __name__ == "__main__":
    main()
