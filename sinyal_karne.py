"""Gonderilen kirilim sinyallerinin karnesi: ucgen_state.json'daki her kirilim icin formasyonu yeniden bulur,
kirilim kapanisindan bugune: hedef / stop / acik ve % getiri (tamami 1xH ve plan: yarisi 0,5xH + stop girise + kalan 1,5xH).
Cikti: karne.json + karne.txt"""
import ast, json, math, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import ucgen_tarayici as u

def sim(h, l, c, b, s, giris, gec, hed, plan):
    D = hed / giris - 1
    t1 = giris * (1 + 0.5 * D) if plan else None
    t2 = giris * (1 + 1.5 * D) if plan else hed
    st, kal, top = gec, 1.0, 0.0
    for i in range(b + 1, len(c)):
        lo, hi = (l[i], h[i]) if s == 1 else (h[i], l[i])
        if s * (lo - st) <= 0:
            return "stop" if kal == 1 else "yarısı kârda, kalan girişte", top + kal * s * (st / giris - 1), i - b
        if t1 and kal == 1 and s * (hi - t1) >= 0:
            top += 0.5 * s * (t1 / giris - 1); kal = 0.5; st = giris
        if s * (hi - t2) >= 0:
            return "hedef", top + kal * s * (t2 / giris - 1), i - b
    return "açık", top + kal * s * (c[-1] / giris - 1), len(c) - 1 - b

def isle(item):
    anahtar, zaman = item
    p, sym, ar, key, tur, yon = anahtar.split("|")
    if tur != "kirilim":
        return None
    try:
        d0 = u.veri_al((p, sym, ar))
    except Exception:  # noqa: BLE001
        d0 = None
    if d0 is None:
        return dict(anahtar=anahtar, hata="veri yok")
    d = u.log_veri(d0); _, ol = u.tara(d)
    def nz(x):
        try:
            return int(round(float(x)))
        except (TypeError, ValueError):
            return str(x)
    try:
        k2 = tuple(nz(x) for x in tuple(ast.literal_eval(key))[:2])
    except Exception:  # noqa: BLE001
        return dict(anahtar=anahtar, hata="anahtar okunamadı")
    aday = [o for o in ol if o["tur"] == "kirilim" and o["yon"] == yon
            and tuple(nz(x) for x in tuple(o["f"]["key"])[:2]) == k2]
    t = np.asarray(d0["t"], float); t = t / 1000 if t[0] > 1e11 else t
    bar = {"4h": 4 * 3600, "1d": 86400}.get(ar, 86400)
    if not aday:   # kod sonradan degistiyse anahtar tutmaz: mesaj zamanina gore ayni yondeki kirilim
        aday = [o for o in ol if o["tur"] == "kirilim" and o["yon"] == yon
                and -bar <= zaman - (t[o["b"]] + bar) <= (3 * bar if ar == "1d" else 2 * bar)]
    if not aday:
        return dict(anahtar=anahtar, hata="formasyon bulunamadı")
    o = min(aday, key=lambda o: abs(t[o["b"]] - zaman))
    b = o["b"]; s = 1 if yon == "yukari" else -1
    h, l, c = (np.asarray(d0[x], float) for x in ("h", "l", "c"))
    giris, gec, hed = c[b], math.exp(o["gecersiz"]) if u.LOG else o["gecersiz"], math.exp(o["hedef"]) if u.LOG else o["hedef"]
    r1 = sim(h, l, c, b, s, giris, gec, hed, False)
    r2 = sim(h, l, c, b, s, giris, gec, hed, True) if s == 1 else None
    desen = ("büyük " if o["f"].get("buyuk") else "") + o["desen"]
    return dict(anahtar=anahtar, p=p, sym=sym, ar=ar, yon=yon, desen=desen, tarih=time.strftime("%Y-%m-%d %H:%M", time.gmtime(t[b])),
                giris=float(giris), stop=float(gec), hedef=float(hed), son=float(c[-1]),
                durum=r1[0], getiri=round(r1[1] * 100, 2), mum=r1[2],
                plan_durum=r2[0] if r2 else None, plan_getiri=round(r2[1] * 100, 2) if r2 else None)

def main():
    durum = json.load(open(u.DURUM_DOSYASI, encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=6) as ex:
        R = [r for r in ex.map(isle, durum.items()) if r]
    gor, T = set(), []
    for r in R:   # ayni sinyal farkli anahtarla iki kez kayitliysa bir kez say
        k = (r.get("p"), r.get("sym"), r.get("ar"), r.get("yon"), r.get("tarih")) if "hata" not in r else r["anahtar"]
        if k not in gor:
            gor.add(k); T.append(r)
    R = T
    json.dump(R, open("karne.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(R), "kırılım,", sum("hata" in r for r in R), "hatalı")

if __name__ == "__main__":
    main()
