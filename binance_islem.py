"""
K69 SHORT otomatik islem (Binance USDT-M vadeli). k69_islem_kos.py her turda cagirir (GitHub disinda calisir).

Calisma (her saat, 4s mum kapanisindan ~7 dk sonra):
  1) Takipteki pozisyonlar: kapandiysa (stop/hedef borsada tetiklendi) kalan emirleri iptal eder, sonucu bildirir;
     30 mumluk zaman stopu dolduysa piyasa emriyle kapatir; stop/hedef emri eksikse yeniden koyar.
  2) Yeni K69 SHORT sinyalleri (filtreden gecenler, ⭐⭐ once): piyasa emriyle short acar, hemen ardindan
     borsaya STOP_MARKET (stop) ve TAKE_PROFIT_MARKET (hedef) emirlerini koyar (closePosition, algo order servisi).
     Stop emri konamazsa pozisyon aninda kapatilir.
Boyut: hesap bakiyesi x risk / (stop - giris). Yildizsiz sinyalde risk yarim. Izole marjin, sabit kaldirac.
Ortam: BINANCE_ORTAM=demo (varsayilan, sahte para) | gercek. Anahtarlar: BINANCE_API_KEY, BINANCE_API_SECRET.
Anahtar yoksa hicbir sey yapmaz. Para cekme izni olmayan anahtar kullan.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from urllib.parse import urlencode

import pandas as pd
import requests
import urllib3.util.connection as _u3c

_u3c.HAS_IPV6 = False      # API anahtari IPv4 adresine kilitli: istekler hep IPv4'ten gitsin

AYAR = {
    "risk": 0.0025,              # islem basi hesap riski (stopa gelirse kayip / bakiye); yildizsizda yarisi
    "maks_acik": 5,              # ayni anda en fazla acik K69 short
    "kaldirac": 3,               # izole; stop %25'ten uzak olamaz (sinyal kurali), likidasyon stopun cok otesinde
    "zaman_stopu_mum": 30,
    "geç_giris_ust": 0.3,        # fiyat stopa (risk x bu) kadar yaklastiysa girme
    "geç_giris_alt": 0.2,        # fiyat hedefe dogru (risk x bu) kadar gittiyse girme
    "kucuk_hesap_maks_risk": 0.02,   # hesaplanan pozisyon Binance'in en kucuk emrinin altindaysa en kucuk emirle gir,
                                     # ama o islemin riski bakiyenin bu oranini asmiyorsa (kucuk hesap modu)
    "maks_gecikme_saat": 3,      # sinyal mumu kapandiktan bu kadar saat sonra artik acma (bilgisayar uykudaydi vb.)
}
URL = {"demo": ["https://demo-fapi.binance.com", "https://testnet.binancefuture.com"],
       "gercek": ["https://fapi.binance.com"]}


class Hata(Exception):
    def __init__(self, kod, mesaj):
        super().__init__(f"{kod}: {mesaj}")
        self.kod = kod


class Istemci:
    def __init__(self, key: str, secret: str, ortam: str):
        self.key, self.secret = key, secret.encode()
        self.ortam = ortam
        self.base = None
        self.fark = 0
        son = None
        for b in URL[ortam]:
            try:
                r = requests.get(b + "/fapi/v1/time", timeout=15)
                r.raise_for_status()
                self.base = b
                self.fark = r.json()["serverTime"] - int(time.time() * 1000)
                break
            except Exception as exc:
                son = exc
        if self.base is None:
            raise RuntimeError(f"Binance ({ortam}) erisilemedi: {son}")
        self._bilgi = None

    def istek(self, yontem: str, yol: str, params: dict | None = None, imzali: bool = True):
        p = {k: v for k, v in (params or {}).items() if v is not None}
        if imzali:
            p["timestamp"] = int(time.time() * 1000) + self.fark
            p["recvWindow"] = 10000
            q = urlencode(p)
            q += "&signature=" + hmac.new(self.secret, q.encode(), hashlib.sha256).hexdigest()
        else:
            q = urlencode(p)
        for deneme in range(3):
            r = requests.request(yontem, f"{self.base}{yol}?{q}", headers={"X-MBX-APIKEY": self.key}, timeout=20)
            if r.status_code in (429, 418) or r.status_code >= 500:
                time.sleep(2 + 3 * deneme)
                continue
            veri = r.json() if r.content else {}
            if r.status_code >= 400:
                raise Hata(veri.get("code", r.status_code), veri.get("msg", r.text[:200]))
            return veri
        raise Hata(r.status_code, r.text[:200])

    # --- yardimcilar
    def filtre(self, sym: str) -> dict:
        if self._bilgi is None:
            self._bilgi = {s["symbol"]: s for s in self.istek("GET", "/fapi/v1/exchangeInfo", imzali=False)["symbols"]}
        s = self._bilgi.get(sym)
        if s is None:
            raise Hata("sembol", f"{sym} bu ortamda yok")
        f = {x["filterType"]: x for x in s["filters"]}
        return {"tick": Decimal(f["PRICE_FILTER"]["tickSize"]), "adim": Decimal(f["MARKET_LOT_SIZE"]["stepSize"]),
                "min_mik": Decimal(f["MARKET_LOT_SIZE"]["minQty"]), "maks_mik": Decimal(f["MARKET_LOT_SIZE"]["maxQty"]),
                "min_tutar": Decimal(f.get("MIN_NOTIONAL", {}).get("notional", "5")), "durum": s.get("status")}

    def hedge(self) -> bool:
        return bool(self.istek("GET", "/fapi/v1/positionSide/dual").get("dualSidePosition"))

    def bakiye(self) -> tuple[float, float]:
        a = self.istek("GET", "/fapi/v2/account")
        return float(a["totalMarginBalance"]), float(a["availableBalance"])

    def pozisyonlar(self) -> dict:
        out = {}
        for p in self.istek("GET", "/fapi/v2/positionRisk"):
            m = float(p["positionAmt"])
            if m != 0:
                out.setdefault(p["symbol"], []).append({"miktar": m, "giris": float(p["entryPrice"]),
                                                        "taraf": p.get("positionSide", "BOTH")})
        return out

    def fiyat(self, sym: str) -> float:
        return float(self.istek("GET", "/fapi/v1/ticker/price", {"symbol": sym}, imzali=False)["price"])

    def algo_acik(self, sym: str) -> list:
        r = self.istek("GET", "/fapi/v1/openAlgoOrders", {"symbol": sym})
        return r if isinstance(r, list) else r.get("orders", [])

    def algo_iptal_hepsi(self, sym: str):
        try:
            self.istek("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": sym})
        except Hata as exc:
            print(f"islem: {sym} algo iptal: {exc}", flush=True)

    def kosullu(self, sym, tip, tetik, hedge, cid):
        return self.istek("POST", "/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": sym, "side": "BUY", "type": tip, "triggerPrice": tetik,
            "closePosition": "true", "workingType": "CONTRACT_PRICE", "priceProtect": "true",
            "positionSide": "SHORT" if hedge else None, "clientAlgoId": cid})

    def piyasa_kapat(self, sym, miktar, hedge):
        return self.istek("POST", "/fapi/v1/order", {
            "symbol": sym, "side": "BUY", "type": "MARKET", "quantity": miktar,
            "positionSide": "SHORT" if hedge else None, "reduceOnly": None if hedge else "true",
            "newOrderRespType": "RESULT"})

    def kar_zarar(self, sym, bas_ms) -> float | None:
        try:
            t = self.istek("GET", "/fapi/v1/userTrades", {"symbol": sym, "startTime": int(bas_ms), "limit": 1000})
            return sum(float(x["realizedPnl"]) - float(x["commission"]) for x in t)
        except Exception as exc:
            print(f"islem: {sym} PnL alinamadi: {exc}", flush=True)
            return None


def _yuvarla(x: float, adim: Decimal, mod=ROUND_HALF_UP) -> str:
    d = (Decimal(str(x)) / adim).quantize(Decimal(1), rounding=mod) * adim
    return format(d.normalize(), "f")


def _cid(tip: str, sym: str) -> str:
    return f"k69{tip}{int(time.time()) % 10**8}{sym[:20]}"


def _fmt(x) -> str:
    x = float(x)
    if x == 0:
        return "0"
    b = max(2, 5 - int(math.floor(math.log10(abs(x)))))
    return f"{x:,.{min(b, 10)}f}"


def calistir(state: dict, gonder) -> None:
    """Her turda cagrilir. state['islem_kuyruk']: short_retest_sistemi'nin bu turda actigi yeni sinyaller."""
    kuyruk = state.pop("islem_kuyruk", [])
    key, sec = os.environ.get("BINANCE_API_KEY", "").strip(), os.environ.get("BINANCE_API_SECRET", "").strip()
    if not key or not sec:
        return
    ortam = "gercek" if os.environ.get("BINANCE_ORTAM", "demo").strip().lower() in ("gercek", "gerçek", "live", "real") else "demo"
    etiket = "💵 GERÇEK HESAP" if ortam == "gercek" else "🧪 DEMO"
    I = state.setdefault("islem", {})
    takip = I.setdefault("acik", {})
    if I.get("ortam") and I["ortam"] != ortam:
        gonder(f"⚠️ K69 işlem botu ortam değişti: {I['ortam']} → {ortam}. Eski ortamın takip listesi sıfırlandı "
               f"({len(takip)} pozisyon; varsa borsada elle kontrol et).")
        takip.clear()
    I["ortam"] = ortam
    try:
        c = Istemci(key, sec, ortam)
        hedge = c.hedge()
        poz = c.pozisyonlar()
    except Exception as exc:
        print(f"islem: baglanti/yetki hatasi: {exc}", flush=True)
        if I.get("son_hata") != str(exc)[:120]:
            gonder(f"⚠️ K69 işlem botu ({etiket}) Binance'e bağlanamadı: {exc}\n"
                   f"API anahtarını, Futures iznini ve IP kısıtını kontrol et. Bu turdaki {len(kuyruk)} sinyal açılmadı.")
            I["son_hata"] = str(exc)[:120]
        return
    I.pop("son_hata", None)
    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)

    # 1) takipteki pozisyonlar
    for sym, t in list(takip.items()):
        p = [x for x in poz.get(sym, []) if x["miktar"] < 0]
        try:
            if not p:
                acik_algo = c.algo_acik(sym)
                neden = "STOP" if any(a.get("clientAlgoId") == t["tp_id"] for a in acik_algo) else \
                        "HEDEF" if any(a.get("clientAlgoId") == t["sl_id"] for a in acik_algo) else "KAPANDI"
                c.algo_iptal_hepsi(sym)
                pnl = c.kar_zarar(sym, t["acilis_ms"])
                R = pnl / t["risk_usdt"] if pnl is not None and t["risk_usdt"] else None
                simge = "✅" if (R or 0) > 0 else "❌"
                gonder(f"{simge} {etiket} K69 SHORT kapandı — {sym}: {neden}\n"
                       f"Giriş {_fmt(t['giris'])} | Kâr/zarar {pnl:+.2f} USDT ({R:+.2f}R)" if R is not None else
                       f"{simge} {etiket} K69 SHORT kapandı — {sym}: {neden} (kâr/zarar alınamadı, Binance'ten kontrol et)")
                I.setdefault("log", []).append({"zaman": str(simdi), "sym": sym, "neden": neden,
                                                "pnl": round(pnl, 4) if pnl is not None else None,
                                                "R": round(R, 3) if R is not None else None, "ortam": ortam})
                del takip[sym]
                continue
            miktar = abs(sum(x["miktar"] for x in p))
            bitis = pd.Timestamp(t["sinyal_zaman"]) + pd.Timedelta(hours=4 * (AYAR["zaman_stopu_mum"] + 1))
            if simdi >= bitis:
                c.algo_iptal_hepsi(sym)
                f = c.filtre(sym)
                r = c.piyasa_kapat(sym, _yuvarla(miktar, f["adim"], ROUND_DOWN), hedge)
                time.sleep(1)
                pnl = c.kar_zarar(sym, t["acilis_ms"])
                R = pnl / t["risk_usdt"] if pnl is not None and t["risk_usdt"] else None
                gonder(f"⏱ {etiket} K69 SHORT zaman stopu — {sym} piyasadan kapatıldı @ {_fmt(r.get('avgPrice', 0))}"
                       + (f" | {pnl:+.2f} USDT ({R:+.2f}R)" if R is not None else ""))
                I.setdefault("log", []).append({"zaman": str(simdi), "sym": sym, "neden": "ZAMAN",
                                                "pnl": round(pnl, 4) if pnl is not None else None,
                                                "R": round(R, 3) if R is not None else None, "ortam": ortam})
                del takip[sym]
                continue
            # koruma emirleri yerinde mi
            ids = {a.get("clientAlgoId") for a in c.algo_acik(sym)}
            for tip, anahtar, tetik in (("STOP_MARKET", "sl_id", t["stop"]), ("TAKE_PROFIT_MARKET", "tp_id", t["hedef"])):
                if t[anahtar] not in ids:
                    t[anahtar] = _cid("s" if tip == "STOP_MARKET" else "t", sym)
                    try:
                        c.kosullu(sym, tip, t["stop_str" if tip == "STOP_MARKET" else "hedef_str"], hedge, t[anahtar])
                        print(f"islem: {sym} eksik {tip} yeniden kondu", flush=True)
                    except Hata as exc:
                        if tip == "STOP_MARKET":
                            c.piyasa_kapat(sym, _yuvarla(miktar, c.filtre(sym)["adim"], ROUND_DOWN), hedge)
                            gonder(f"⚠️ {etiket} {sym}: stop emri yeniden konamadı ({exc}), pozisyon piyasadan kapatıldı.")
                            c.algo_iptal_hepsi(sym)
                            del takip[sym]
                            break
                        print(f"islem: {sym} hedef emri konamadi: {exc}", flush=True)
        except Exception as exc:
            print(f"islem: {sym} takip hatasi: {exc}", flush=True)

    # 2) yeni sinyaller
    if not kuyruk:
        return
    kuyruk.sort(key=lambda x: -x["yildiz"])
    try:
        bakiye, serbest = c.bakiye()
    except Exception as exc:
        gonder(f"⚠️ {etiket} bakiye alınamadı ({exc}); {len(kuyruk)} sinyal açılmadı.")
        return
    sinirda = []
    for s in kuyruk:
        sym = s["sym"]
        try:
            if len(takip) >= AYAR["maks_acik"]:
                sinirda.append(sym.replace("USDT", ""))
                continue
            if sym in poz or sym in takip:
                gonder(f"ℹ️ {etiket} {sym} K69 SHORT açılmadı: bu coinde zaten açık pozisyon var.")
                continue
            kapanis = pd.Timestamp(s["zaman"]) + pd.Timedelta(hours=4)
            if simdi - kapanis > pd.Timedelta(hours=AYAR["maks_gecikme_saat"]):
                gonder(f"ℹ️ {etiket} {sym} K69 SHORT açılmadı: sinyal {int((simdi - kapanis).total_seconds() // 3600)} saat önce "
                       f"oluştu (bot o sırada çalışmıyordu), geç giriş yapılmıyor.")
                continue
            f = c.filtre(sym)
            if f["durum"] != "TRADING":
                continue
            e0, st, hd = s["giris"], s["stop"], s["hedef"]
            R0 = st - e0
            fy = c.fiyat(sym)
            if fy >= st - AYAR["geç_giris_ust"] * R0 or fy <= e0 - AYAR["geç_giris_alt"] * R0:
                gonder(f"ℹ️ {etiket} {sym} K69 SHORT açılmadı: fiyat sinyalden bu yana fazla oynadı "
                       f"(sinyal {_fmt(e0)}, şimdi {_fmt(fy)}).")
                continue
            risk_oran = AYAR["risk"] * (0.5 if s["yildiz"] == 0 else 1.0)
            risk_usdt = bakiye * risk_oran
            mik = Decimal(_yuvarla(risk_usdt / (st - fy), f["adim"], ROUND_DOWN))
            mik = min(mik, f["maks_mik"])
            tutar = float(mik) * fy
            kucuk_not = ""
            if mik < f["min_mik"] or Decimal(str(tutar)) < f["min_tutar"]:
                gerek = max(float(f["min_tutar"]) * 1.1 / fy, float(f["min_mik"]))
                mik = Decimal(_yuvarla(gerek, f["adim"], ROUND_UP))
                tutar = float(mik) * fy
                risk_min = float(mik) * (st - fy)
                if risk_min > bakiye * AYAR["kucuk_hesap_maks_risk"]:
                    gonder(f"ℹ️ {etiket} {sym} K69 SHORT açılmadı: en küçük emirle ({tutar:.1f} USDT) risk "
                           f"{risk_min:.2f} USDT olurdu, bakiyenin %{AYAR['kucuk_hesap_maks_risk'] * 100:.0f} sınırını aşıyor.")
                    continue
                kucuk_not = "\n(Küçük hesap modu: Binance'in en küçük emir tutarıyla girildi.)"
            if tutar / AYAR["kaldirac"] > serbest * 0.95:
                gonder(f"ℹ️ {etiket} {sym} K69 SHORT açılmadı: yetersiz serbest marjin ({serbest:.2f} USDT).")
                continue
            try:
                c.istek("POST", "/fapi/v1/marginType", {"symbol": sym, "marginType": "ISOLATED"})
            except Hata as exc:
                if str(exc.kod) != "-4046":          # zaten izole
                    print(f"islem: {sym} marginType: {exc}", flush=True)
            c.istek("POST", "/fapi/v1/leverage", {"symbol": sym, "leverage": AYAR["kaldirac"]})
            acilis_ms = int(time.time() * 1000) + c.fark - 5000
            emir = c.istek("POST", "/fapi/v1/order", {
                "symbol": sym, "side": "SELL", "type": "MARKET", "quantity": format(mik.normalize(), "f"),
                "positionSide": "SHORT" if hedge else None, "newOrderRespType": "RESULT"})
            giris = float(emir.get("avgPrice") or fy)
            dolan = float(emir.get("executedQty") or mik)
            stop_str = _yuvarla(st, f["tick"])
            hedef_str = _yuvarla(hd, f["tick"])
            sl_id, tp_id = _cid("s", sym), _cid("t", sym)
            try:
                c.kosullu(sym, "STOP_MARKET", stop_str, hedge, sl_id)
            except Exception as exc:
                c.piyasa_kapat(sym, format(Decimal(str(dolan)).normalize(), "f"), hedge)
                gonder(f"⚠️ {etiket} {sym}: short açıldı ama stop emri konamadı ({exc}); pozisyon hemen kapatıldı.")
                continue
            tp_not = ""
            try:
                c.kosullu(sym, "TAKE_PROFIT_MARKET", hedef_str, hedge, tp_id)
            except Exception as exc:
                tp_not = f"\n⚠️ Hedef emri konamadı ({exc}); bir sonraki turda tekrar denenecek."
            gercek_risk = dolan * (st - giris)
            takip[sym] = {"sinyal_zaman": str(s["zaman"]), "giris": giris, "miktar": dolan, "stop": st, "hedef": hd,
                          "stop_str": stop_str, "hedef_str": hedef_str, "sl_id": sl_id, "tp_id": tp_id,
                          "risk_usdt": gercek_risk, "acilis_ms": acilis_ms, "yildiz": s["yildiz"]}
            serbest -= tutar / AYAR["kaldirac"]
            gonder(f"🤖 {etiket} K69 SHORT AÇILDI — {sym}\n"
                   f"Giriş {_fmt(giris)} | miktar {_fmt(dolan)} (~{dolan * giris:.0f} USDT, {AYAR['kaldirac']}x izole)\n"
                   f"Stop {stop_str} | Hedef {hedef_str} (borsada emir olarak bekliyor)\n"
                   f"Risk {gercek_risk:.2f} USDT (bakiyenin %{gercek_risk / bakiye * 100:.2f})" + kucuk_not + tp_not)
        except Exception as exc:
            print(f"islem: {sym} acma hatasi: {exc}", flush=True)
            gonder(f"⚠️ {etiket} {sym} K69 SHORT açılırken hata: {exc}")
    if sinirda:
        gonder(f"ℹ️ {etiket} açık short sınırı ({AYAR['maks_acik']}) dolu; açılmayan {len(sinirda)} sinyal: {', '.join(sinirda)}")


def ozet(state: dict) -> str:
    I = state.get("islem") or {}
    if not I.get("ortam"):
        return ""
    etiket = "GERÇEK" if I["ortam"] == "gercek" else "DEMO"
    s = [f"🤖 K69 işlem botu ({etiket}): açık {len(I.get('acik', {}))} short"
         + (": " + ", ".join(I["acik"]) if I.get("acik") else "")]
    log = [x for x in I.get("log", []) if x.get("ortam") == I["ortam"] and x.get("R") is not None]
    if log:
        rr = [x["R"] for x in log]
        s.append(f"Bot işlemleri ({etiket}, toplam): {len(rr)} | isabet %{100 * sum(r > 0 for r in rr) / len(rr):.0f} | "
                 f"{sum(rr):+.2f}R | {sum(x['pnl'] or 0 for x in log):+.2f} USDT")
    return "\n".join(s)
