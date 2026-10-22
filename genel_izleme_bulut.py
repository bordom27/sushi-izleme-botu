"""
KIRILIM69 PRO v6 - TELEGRAM IZLEME BOTU (Binance, 4 saatlik)
================================================================================
BU SCRIPT GERCEK ISLEM ACMAZ. GitHub Actions tarafindan periyodik tetiklenir.

TradingView'daki "Kirilim69 PRO" gostergesiyle AYNI mantik (kirilim_v6.py):
long + short, BTC piyasa elegi (long icin BTC > gunluk EMA200), hacimli
kirilim / retest / teyit girisi, yapisal stop, fib + engel bazli TP1/TP2,
TP1'de %90 kar al + stop basabas+0.1R, chandelier trailing, zaman stopu.

Nasil calisir:
  Her calistirmada her coinin 4 saatlik gecmisi SABIT bir baslangictan
  itibaren yeniden hesaplanir (gostergeyle ayni sonuc) ve sadece son
  calistirmadan beri KAPANAN mumlardaki olaylar Telegram'a gonderilir.
  GitHub calistirmayi geciktirse / atlasa bile sinyal kacmaz.

Gerekli ortam degiskenleri (GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

import kirilim_v6 as k
import veri
import short_retest as SR
import zarattini as Z
from coin_listesi import CEKIRDEK, COINLER, GENISLIK_COINLER, VADELI_AD, VADELI_YOK

CONFIG = {
    "COINLER": COINLER,
    "VERI_BAS_4H": "2024-06-01",     # sabit baslangic: hesap her calistirmada ayni kalir
    "VERI_BAS_1D": "2019-06-01",
    "STATE_FILE": "izleme_state.json",
    "ISTEK_BEKLEME": 0.12,

    "BILDIR_KIRILIM": True,          # "kirilim oldu, retest bekleniyor" on uyarilari
    "BILDIR_TRAIL_R": 0.5,           # TP1 sonrasi iz suren stop en az bu kadar R ilerlerse bildir
    "GUNLUK_OZET_SAAT_UTC": 18,      # 21:00 Turkiye saati
    "GECIKME_UYARI_SAAT": 3,         # olay bu kadar saatten eskiyse mesajda belirt
    "BAYAT_SAAT": 12,
    # KALABALIK UYARISI (Ekim 2026 testi): buyuk oyuncularin (top trader) pozisyon orani girisin
    # yonune bu kadar yigilmissa (long'da L/S > esik, short'ta S/L > esik) islem basi getiri
    # dort test grubunun dordunde de belirgin dusuk cikti -> riski yariya indirme onerisi.
    "KALABALIK_ESIK": 1.69,
    # IKINCI SISTEM: gunluk trend portfoyu (zarattini.py). Agirliklar sermayenin orani; 1.0 = v6.6'nin islem basi
    # %0.5 riskiyle ayni oynaklik (testte birlikte: 2020+ yillik ~%23, Sharpe ~1.9). Ikisini birlikte buyutmek icin
    # hesap_risk ile ayni oranda artir.
    "TREND_PORTFOY": True,
    "TREND_OLCEK": 1.0,
    # UCUNCU SISTEM: K69 SHORT - dusuk hacimli retest short (short_retest.py), tum likit USDT-M vadeli sozlesmeler.
    "SHORT_RETEST": True,
    "SHORT_VERI_BAS": "2026-04-01",    # sabit baslangic (160 mum seviye + 180 mum hacim medyani icin yeterli)
    "SHORT_MAKS_ACIK": 5,
    "SHORT_RISK": "%0.5 (ilk ay %0.25)",                # bundan eski olaylar tek tek degil, tek ozet mesajinda gonderilir
}

TR = timezone(timedelta(hours=3))
YON = {1: "LONG", -1: "SHORT"}
TIP_ADI = {"GUCLU KIRILIM": "GÜÇLÜ KIRILIM", "KIRILIM": "KIRILIM", "RETEST": "RETEST", "TEYIT": "TEYİT"}
NEDEN_ADI = {"STOP": "STOP", "STOP_TP1": "STOP (TP1 sonrası iz süren stop)", "TP2": "TP2 (final)",
             "ZAMAN": "ZAMAN STOPU", "TREND": "TREND ÇIKIŞI",
             "BASARISIZ": "BAŞARISIZ KIRILIM (fiyat kırılan seviyenin gerisine döndü, stop beklenmeden çıkıldı)"}


# ------------------------------------------------------------------------------------
# YARDIMCILAR
# ------------------------------------------------------------------------------------
def fmt(x: float) -> str:
    """Fiyati okunur bicimde yaz (PEPE gibi kucuk fiyatlarda yeterli basamak)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    ax = abs(x)
    if ax == 0:
        return "0"
    basamak = max(2, min(10, 4 - int(math.floor(math.log10(ax)))))
    return f"{x:.{basamak}f}"


def pct(a: float, b: float) -> str:
    return f"%{(a / b - 1) * 100:+.2f}"


def tr_saat(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(TR).strftime("%d.%m %H:%M")


def grafik_linki(sym: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}&interval=240"


def send_telegram(mesaj: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    print("-" * 60 + "\n" + mesaj)
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    parcalar, buf = [], ""
    for blok in mesaj.split("\n\n"):
        if buf and len(buf) + len(blok) + 2 > 3900:
            parcalar.append(buf)
            buf = ""
        buf = (buf + "\n\n" + blok) if buf else blok
    if buf:
        parcalar.append(buf)
    parcalar = [p[i:i + 3900] for p in parcalar for i in range(0, len(p), 3900)]
    for parca in parcalar:
        for deneme in range(3):
            try:
                resp = requests.post(url, data={"chat_id": chat_id, "text": parca,
                                                 "disable_web_page_preview": "true"}, timeout=15)
                if resp.ok:
                    break
                print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")
                if resp.status_code == 429:
                    time.sleep(3 + deneme * 3)
            except Exception as exc:
                print(f"Telegram gonderim hatasi: {exc}")
                time.sleep(2)
        time.sleep(0.4)


def load_state(cfg) -> dict:
    if os.path.exists(cfg["STATE_FILE"]):
        with open(cfg["STATE_FILE"], "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict, cfg):
    with open(cfg["STATE_FILE"], "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)


# ------------------------------------------------------------------------------------
# MESAJLAR
# ------------------------------------------------------------------------------------
def gecikme_notu(olay_zaman, cfg) -> str:
    kapanis = pd.Timestamp(olay_zaman) + pd.Timedelta(hours=4)
    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
    saat = (simdi - kapanis).total_seconds() / 3600
    if saat >= cfg["GECIKME_UYARI_SAAT"]:
        return f"\n⚠️ Bu sinyal {saat:.0f} saat önce kapanan mumda oluştu (GitHub gecikmesi). Fiyatı kontrol et."
    return ""


def kalabalik_orani(sym: str, zaman_ms: int):
    """Binance vadeli 'top trader' long/short POZISYON orani (giris anina en yakin 5 dk degeri)."""
    for ad in (sym, "1000" + sym):
        try:
            r = requests.get("https://www.binance.com/futures/data/topLongShortPositionRatio",
                             params={"symbol": ad, "period": "5m", "limit": 1, "endTime": zaman_ms},
                             headers=veri.HEADERS, timeout=10)
            if r.ok:
                d = r.json()
                if isinstance(d, list) and d:
                    return float(d[-1]["longShortRatio"])
        except Exception as exc:
            print(f"kalabalik orani alinamadi {ad}: {exc}")
    return None


def kalabalik_satiri(sym, o: k.Olay, cfg, v):
    kapanis = pd.Timestamp(o.zaman) + pd.Timedelta(hours=4)
    ls = kalabalik_orani(sym, int(kapanis.tz_localize("UTC").timestamp() * 1000) if kapanis.tzinfo is None
                         else int(kapanis.timestamp() * 1000))
    if not ls or ls <= 0:
        return ""
    yonlu = ls if o.yon == 1 else 1 / ls
    oran_txt = f"büyük oyuncular L/S {ls:.2f}"
    if yonlu > cfg["KALABALIK_ESIK"]:
        yari = k.PARAMS["hesap_risk"] / 2
        return (f"⚠️ Kalabalık zaten {YON[o.yon]} tarafında ({oran_txt}). Testte bu durumda işlemler belirgin zayıf: "
                f"riski yarıya indir → hesabın %{yari:g}'i (sermayenin %{v['poz_pct'] / 2:.1f}).\n")
    return f"Kalabalık: {oran_txt} — {YON[o.yon]} tarafı aşırı kalabalık değil ✓\n"


def mesaj_giris(sym, o: k.Olay, cfg) -> str:
    v = o.veri
    d = o.yon
    r = v["risk"]
    tp1_r = abs(v["tp1"] - v["giris"]) / r
    tp2_r = abs(v["tp2"] - v["giris"]) / r
    simge = "🟢" if d == 1 else "🔴"
    return (
        f"{simge} {YON[d]} GİRİŞ — {sym} (4s)\n"
        + (f"Vadelide: {VADELI_AD[sym]} (fiyat x1000)\n" if sym in VADELI_AD else "")
        + ("⚠️ Binance vadelide kontratı yok (sadece spot)\n" if sym in VADELI_YOK else "") +
        f"Tip: {TIP_ADI.get(v['tip'], v['tip'])} | Kalite: {v['kalite']}\n"
        f"Giriş: {fmt(v['giris'])}  (mum kapanışı {tr_saat(o.zaman + pd.Timedelta(hours=4))})\n"
        f"Stop: {fmt(v['stop'])}  ({pct(v['stop'], v['giris'])})\n"
        f"TP1: {fmt(v['tp1'])}  ({tp1_r:.1f}R, {v['tp1_kay']}) → pozisyonun %{k.PARAMS['tp1_pct']:g} kadarını kapat\n"
        f"TP2: {fmt(v['tp2'])}  ({tp2_r:.1f}R, {v['tp2_kay']}) → kalan %{100 - k.PARAMS['tp1_pct']:g}\n"
        f"Pozisyon büyüklüğü (hesabın %{k.PARAMS['hesap_risk']:g}'i riskte): sermayenin %{v['poz_pct']:.1f}\n"
        + kalabalik_satiri(sym, o, cfg, v) +
        f"TP1 sonrası stop giriş+{k.PARAMS['be_buf_r']:g}R'ye çekilir ve {k.PARAMS['trail_atr_mult']:g} ATR iz süren stopa geçer. "
        f"İlk {k.PARAMS['bc_bar']} mumda kapanış kırılan seviyenin {k.PARAMS['bc_atr']:g} ATR gerisine dönerse stopu bekleme, çık (bot bildirir). "
        f"{k.PARAMS['time_stop_bars']} mum (~{k.PARAMS['time_stop_bars'] * 4 / 24:.1f} gün) içinde TP1 gelmez ve kâr {k.PARAMS['time_stop_min_r']:g}R'nin altındaysa çık.\n"
        f"{grafik_linki(sym)}" + gecikme_notu(o.zaman, cfg)
    )


def guven_etiketi(metin: str, n: int, yon: int) -> str:
    """Giris mesajina guven etiketi ekler (ilk satirin altina)."""
    yon_ad = YON[yon]
    if n >= 8:
        satir = (f"⭐⭐ ÇOK YÜKSEK GÜVEN: son 24 saatte {n} coin aynı yönde ({yon_ad}) sinyal verdi "
                 f"(testte bu durumda isabet ~%80).")
    elif n >= 5:
        satir = (f"⭐ YÜKSEK GÜVEN: son 24 saatte {n} coin aynı yönde ({yon_ad}) sinyal verdi "
                 f"(testte bu durumda isabet ~%73).")
    else:
        satir = (f"Tekil sinyal: son 24 saatte aynı yönde sadece {n} sinyal "
                 f"(testte bu durumda isabet ~%53, işlem başı ~+0.06R) — sadece yıldızlıları alıyorsan pas geç.")
    ilk, _, kalan = metin.partition("\n")
    return ilk + "\n" + satir + ("\n" + kalan if kalan else "")


def mesaj_tp1(sym, o: k.Olay, cfg) -> str:
    v = o.veri
    return (f"🟠 TP1 — {sym} {YON[o.yon]}\n"
            f"TP1 {fmt(v['fiyat'])} geldi: pozisyonun %{k.PARAMS['tp1_pct']:g} kadarını kapat.\n"
            f"Yeni stop: {fmt(v['yeni_stop'])} (giriş {fmt(v['giris'])} + 0.1R). Kalan için TP2: {fmt(v['tp2'])}"
            + gecikme_notu(o.zaman, cfg))


def mesaj_cikis(sym, o: k.Olay, cfg) -> str:
    v = o.veri
    r = v["sonuc_r"]
    simge = "✅" if r > 0 else "❌"
    fiyat_deg = (v["cikis"] / v["giris"] - 1) * 100 * o.yon
    return (f"{simge} {YON[o.yon]} KAPANDI — {sym}: {NEDEN_ADI.get(v['neden'], v['neden'])}\n"
            f"Çıkış: {fmt(v['cikis'])} | Giriş: {fmt(v['giris'])} ({tr_saat(v['giris_zaman'] + pd.Timedelta(hours=4))})\n"
            f"Sonuç: {r:+.2f}R (komisyon dahil){' — TP1 alınmıştı' if v['tp1_done'] else ''} | "
            f"son kısmın fiyat değişimi %{fiyat_deg:+.2f}"
            + gecikme_notu(o.zaman, cfg))


def mesaj_kirilim(sym, o: k.Olay) -> str:
    v = o.veri
    ne = "direnç" if o.yon == 1 else "destek"
    return (f"🟡 {YON[o.yon]} KIRILIM — {sym}: {ne} {fmt(v['seviye'])} kırıldı (kalite {v['kalite']}).\n"
            f"Hacim/mum gücü doğrudan giriş için yetmedi; retest veya teyit mumu bekleniyor (en fazla 6 mum). "
            f"Giriş olursa ayrıca bildirilecek.")


def mesaj_iptal(sym, o: k.Olay) -> str:
    neden = "sahte kırılım (fiyat seviyenin gerisine döndü)" if o.tur == "SAHTE" else "6 mumda retest/teyit gelmedi"
    return f"⚪ {sym} {YON[o.yon]} kırılım iptal: {neden}."


def mesaj_trail(sym, acik: dict, eski_stop: float) -> str:
    return (f"🔧 STOP GÜNCELLE — {sym} {YON[acik['yon']]}: iz süren stop {fmt(eski_stop)} → {fmt(acik['stop'])}. "
            f"Anlık: {acik['anlik_r']:+.2f}R")


# ------------------------------------------------------------------------------------
# ESKI SISTEM POZISYONLARI (v6 oncesi acilmis) - kapanana kadar eski kurallarla takip
# ------------------------------------------------------------------------------------
def eski_pozisyonlari_yonet(state: dict, veriler: dict):
    eski = state.get("eski_pozisyonlar") or {}
    for label in list(eski.keys()):
        pos = eski[label]
        sym = label.split("] ")[-1]
        df = veriler.get(sym)
        if df is None and label.startswith("[KRIPTO]"):
            try:
                df = veri.mumlar(sym, "4h", pd.Timestamp(pos["entry_time"]) - pd.Timedelta(days=10))
            except Exception as exc:
                print(f"eski pozisyon verisi alinamadi {sym}: {exc}")
                continue
        if df is None or not label.startswith("[KRIPTO]"):
            if not label.startswith("[KRIPTO]"):
                send_telegram(f"ℹ️ [ESKİ SİSTEM] {label} artık takip edilmiyor (bot sadece kripto izliyor). "
                              f"Stop {pos['stop']:.4f}, TP1 {pos['tp1_price']:.4f}, TP2 {pos['tp2_price']:.4f}.")
                del eski[label]
            continue
        h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        pc = np.concatenate([[np.nan], c[:-1]])
        tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
        atr = pd.Series(tr).rolling(14).mean().shift(1).to_numpy()
        son = pd.Timestamp(pos.get("son_kontrol") or pos["entry_time"])
        idx = np.where(df["open_time"] > son)[0]
        kapandi = False
        for i in idx:
            row_t = df["open_time"].iloc[i]
            if l[i] <= pos["stop"]:
                pnl = (pos["stop"] / pos["entry"] - 1) * 100
                send_telegram(f"[ESKİ SİSTEM] {label}: STOP ({fmt(pos['stop'])}). Giriş {fmt(pos['entry'])} | Sonuç %{pnl:+.2f}")
                state.setdefault("trade_log", []).append({"zaman": str(row_t), "varlik": label, "sonuc": "STOP", "pnl_pct": round(pnl, 2), "sistem": "eski"})
                kapandi = True
                break
            elif not pos["tp1_done"] and h[i] >= pos["tp1_price"]:
                pos["tp1_done"] = True
                pos["stop"] = pos["entry"]
                send_telegram(f"[ESKİ SİSTEM] {label}: TP1 ({fmt(pos['tp1_price'])}). Stop girişe çekildi.")
            elif h[i] >= pos["tp2_price"]:
                pnl = (pos["tp2_price"] / pos["entry"] - 1) * 100
                send_telegram(f"[ESKİ SİSTEM] {label}: TP2 final ({fmt(pos['tp2_price'])}). Sonuç %{pnl:+.2f}")
                state.setdefault("trade_log", []).append({"zaman": str(row_t), "varlik": label, "sonuc": "TP2_FINAL", "pnl_pct": round(pnl, 2), "sistem": "eski"})
                kapandi = True
                break
            elif pos["tp1_done"] and not math.isnan(atr[i]):
                aday = c[i] - 2.5 * atr[i]
                if aday > pos["stop"]:
                    pos["stop"] = aday
            pos["son_kontrol"] = str(row_t)
        if kapandi:
            del eski[label]
    state["eski_pozisyonlar"] = eski


# ------------------------------------------------------------------------------------
# GECIS: eski state -> v6 state
# ------------------------------------------------------------------------------------
def gecis_yap(state: dict) -> dict:
    if state.get("versiyon") == 6:
        return state
    eski_poz = {k_: v for k_, v in (state.get("positions") or {}).items() if v}
    yeni = {
        "versiyon": 6,
        "gecis_zamani": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "son_bar": {},
        "bildirilen": [],
        "son_stop_bildirimi": {},
        "trade_log": state.get("trade_log", []),
        "eski_pozisyonlar": eski_poz,
        "son_ozet_gunu": None,
    }
    return yeni


# ------------------------------------------------------------------------------------
# GUNLUK OZET
# ------------------------------------------------------------------------------------
def gunluk_ozet(state, sonuclar, btc_bilgi) -> str:
    satir = [f"📊 GÜNLÜK ÖZET — {datetime.now(TR).strftime('%d.%m.%Y %H:%M')}"]
    satir.append(btc_bilgi)
    acik = [(s, r.acik) for s, r in sonuclar.items() if r.acik]
    if acik:
        satir.append(f"\nAçık pozisyonlar ({len(acik)}):")
        for s, a in sorted(acik, key=lambda x: -x[1]["anlik_r"]):
            satir.append(f"• {s} {YON[a['yon']]} giriş {fmt(a['giris'])} | stop {fmt(a['stop'])}"
                         f"{' (TP1 alındı)' if a['tp1_done'] else ' | TP1 ' + fmt(a['tp1'])} | TP2 {fmt(a['tp2'])} | "
                         f"anlık {a['anlik_r']:+.2f}R")
    else:
        satir.append("\nAçık pozisyon yok.")
    bek = [(s, r.bekleyen) for s, r in sonuclar.items() if r.bekleyen]
    if bek:
        satir.append("Retest bekleyen kırılımlar: " + ", ".join(f"{s} {YON[b['yon']]} @ {fmt(b['seviye'])}" for s, b in bek))
    eski = state.get("eski_pozisyonlar") or {}
    if eski:
        satir.append("Eski sistemden açık: " + ", ".join(
            f"{x.split('] ')[-1]} (stop {fmt(p['stop'])}, TP1 {fmt(p['tp1_price'])}{' ✓' if p['tp1_done'] else ''}, TP2 {fmt(p['tp2_price'])})"
            for x, p in eski.items()))
    tp = state.get("trend_portfoy") or {}
    if tp:
        satir.append(f"Günlük trend portföyü ({len(tp)} coin, sermayenin %{100 * sum(tp.values()):.1f}'i): " + ", ".join(
            f"{x.replace('USDT', '')} %{100 * v:.2f}" for x, v in sorted(tp.items(), key=lambda y: -y[1])))
    hazir_l = [s for s, r in sonuclar.items() if r.filtre.get("long_hazir") and not r.acik]
    hazir_s = [s for s, r in sonuclar.items() if r.filtre.get("short_hazir") and not r.acik]
    satir.append(f"Elekleri geçmiş, kırılım bekleyen: LONG {len(hazir_l)} | SHORT {len(hazir_s)}")

    def _izle(liste, yon):
        out = []
        for s in liste:
            r = sonuclar[s]
            f = r.filtre
            sev = f.get("direnc") if yon == 1 else f.get("destek")
            atr = f.get("atr")
            if not sev or not r.son_kapanis:
                continue
            esik = sev + yon * k.PARAMS["break_buf_atr"] * (atr or 0)   # kirilim icin kapanisin gecmesi gereken seviye
            uzak = (esik / r.son_kapanis - 1) * 100
            out.append((abs(uzak), f"• {s}: {'üstünde' if yon == 1 else 'altında'} 4s kapanış {fmt(esik)} "
                                   f"(şu an {fmt(r.son_kapanis)}, %{uzak:+.1f} uzakta) + hacim ortalamanın {k.PARAMS['vol_mult']:g} katı"))
        return [m for _, m in sorted(out)]

    if hazir_l:
        satir.append("LONG takip (direnç kırılırsa sinyal):")
        satir.extend(_izle(hazir_l, 1))
    if hazir_s:
        satir.append("SHORT takip (destek kırılırsa sinyal):")
        satir.extend(_izle(hazir_s, -1))

    # son 30 gun v6 istatistigi (bildirilen kapanislardan)
    log = [t for t in state.get("trade_log", []) if t.get("sistem") == "v6"]
    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
    son30 = [t for t in log if pd.Timestamp(t["zaman"]) >= simdi - pd.Timedelta(days=30)]
    if son30:
        rr = [t["sonuc_r"] for t in son30]
        satir.append(f"Son 30 gün (canlı): {len(rr)} işlem | isabet %{100 * sum(x > 0 for x in rr) / len(rr):.0f} | "
                     f"toplam {sum(rr):+.2f}R")
    return "\n".join(satir)


# ------------------------------------------------------------------------------------
# K69 SHORT - dusuk hacimli retest short (tum likit vadeli coinler)
# ------------------------------------------------------------------------------------
def vadeli_semboller() -> list[str]:
    info = veri._get("/fapi/v1/exchangeInfo", {}, veri.FAPI_URLS)
    return sorted(s["symbol"] for s in info["symbols"]
                  if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"
                  and s.get("status") == "TRADING" and s.get("underlyingType", "COIN") == "COIN")


def _vadeli_df(sym: str, cfg) -> pd.DataFrame:
    df = veri.mumlar_onbellekli("F:" + sym, "4h", cfg["SHORT_VERI_BAS"])
    return df.set_index("open_time").rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[
        ["o", "h", "l", "c", "v"]]


def short_grafik(sym: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}.P&interval=240"


def short_retest_sistemi(state: dict, cfg: dict) -> list[str]:
    """Yeni retest short sinyallerini ve acik short'larin kapanislarini mesaj olarak dondurur."""
    try:
        semboller = vadeli_semboller()
    except Exception as exc:
        print(f"short: vadeli listesi alinamadi: {exc}", flush=True)
        return []
    son_bar = state.setdefault("short_son_bar", {})
    acik = state.setdefault("short_acik", {})
    ilk = not son_bar
    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
    bayat = simdi - pd.Timedelta(hours=cfg["BAYAT_SAAT"] + 4)
    veri_ = {}
    kapanis_m, giris_m = [], []
    hata = 0
    for sym in semboller:
        try:
            g = _vadeli_df(sym, cfg)
        except Exception as exc:
            hata += 1
            print(f"short {sym} veri yok: {exc}", flush=True)
            continue
        finally:
            time.sleep(cfg["ISTEK_BEKLEME"])
        if len(g) < 250:
            continue
        veri_[sym] = g
    # 1) acik short'lari takip et
    for anahtar, poz in list(acik.items()):
        sym = poz["sym"]
        g = veri_.get(sym)
        if g is None:
            continue
        r = SR.sonuc_takip(g, poz)
        if r is None:
            continue
        neden, fiyat, t, R = r
        simge = "✅" if R > 0 else "❌"
        ad = {"HEDEF": "HEDEF (0.5R)", "STOP": "STOP", "ZAMAN": "ZAMAN STOPU (30 mum)"}[neden]
        kapanis_m.append(f"{simge} SHORT RETEST kapandı — {sym}: {ad} @ {fmt(fiyat)} ({tr_saat(t + pd.Timedelta(hours=4))})\n"
                         f"Giriş {fmt(poz['giris'])} | Sonuç {R:+.2f}R")
        state.setdefault("trade_log", []).append({"zaman": str(t), "varlik": sym, "yon": "SHORT", "sonuc": neden,
                                                  "sonuc_r": round(float(R), 3), "sistem": "short_retest"})
        del acik[anahtar]
    # 2) yeni sinyaller
    for sym, g in veri_.items():
        onceki = son_bar.get(sym)
        son_bar[sym] = str(g.index[-1])
        if onceki is None:
            continue                     # yeni gorulen sembol: gecmis sinyaller gonderilmez
        for x in SR.sinyaller(g):
            if x["zaman"] <= pd.Timestamp(onceki):
                continue
            if any(p["sym"] == sym for p in acik.values()):
                continue
            anahtar = f"{sym}|{x['zaman']}"
            poz = {"sym": sym, "zaman": str(x["zaman"]), "giris": float(x["giris"]), "stop": float(x["stop"]),
                   "hedef": float(x["hedef"]), "yildiz": int(x["yildiz"])}
            acik[anahtar] = poz
            if x["zaman"] < bayat:           # bot uzun sure calisamadiysa eski sinyal gonderilmez (takip edilir)
                continue
            yild = {2: "⭐⭐ GÜÇLÜ", 1: "⭐", 0: "(yıldızsız — riski yarıya indir)"}[x["yildiz"]]
            isabet = {2: "~%87", 1: "~%82", 0: "~%77"}[x["yildiz"]]
            ad = sym.replace("USDT", "")
            giris_m.append(
                f"🔻 SHORT RETEST {yild} — {ad} (vadeli {sym})\n"
                f"Giriş ~{fmt(x['giris'])} (4s kapanış {tr_saat(x['zaman'] + pd.Timedelta(hours=4))}) | "
                f"Stop {fmt(x['stop'])} (%{x['risk_pct']:.1f}) | Hedef {fmt(x['hedef'])} (0.5R, tamamını kapat)\n"
                f"Kırılan destek {fmt(x['seviye'])}: kırılmadan önce {x['dokunus']} kez test edilmiş, "
                f"{tr_saat(x['kirilim_zaman'] + pd.Timedelta(hours=4))}'te kırıldı ({x['seviye_mum']} mumluk dip). "
                f"Geri yükseliş düşük hacimli (ortalamanın {x['hacim_orani']:.2f} katı), 2 yeşil mumdan sonra ret.\n"
                f"Zaman stopu: 30 mum (5 gün). Testte isabet {isabet}. Coin günlük hacmi ~{x['gunluk_hacim'] / 1e6:.0f}M$.\n"
                f"{short_grafik(sym)}")
    if hata > len(semboller) // 2:
        print(f"short: {hata} sembolde veri hatasi", flush=True)
    mesajlar = kapanis_m[:]
    if giris_m:
        n_acik = len(acik)
        not_ = (f"Açık retest short: {n_acik} (öneri: aynı anda en fazla {cfg['SHORT_MAKS_ACIK']}, işlem başı risk {cfg['SHORT_RISK']})")
        if n_acik > cfg["SHORT_MAKS_ACIK"]:
            not_ += " — limit aşıldı, ⭐⭐ olanları öncelikle."
        mesajlar.append("\n\n".join(giris_m) + "\n\n" + not_)
    if ilk:
        mesajlar = []
    return mesajlar


def short_ozet(state) -> str:
    acik = state.get("short_acik") or {}
    satir = []
    if acik:
        satir.append(f"K69 SHORT açık retest short ({len(acik)}): " + ", ".join(
            f"{p['sym'].replace('USDT', '')} (giriş {fmt(p['giris'])}, stop {fmt(p['stop'])}, hedef {fmt(p['hedef'])})"
            for p in acik.values()))
    else:
        satir.append("K69 SHORT: açık retest short yok.")
    log = [t for t in state.get("trade_log", []) if t.get("sistem") == "short_retest"]
    simdi = pd.Timestamp.now(tz="UTC").tz_localize(None)
    son30 = [t for t in log if pd.Timestamp(t["zaman"]) >= simdi - pd.Timedelta(days=30)]
    if son30:
        rr = [t["sonuc_r"] for t in son30]
        satir.append(f"K69 SHORT son 30 gün (canlı): {len(rr)} işlem | isabet %{100 * sum(x > 0 for x in rr) / len(rr):.0f} | "
                     f"toplam {sum(rr):+.2f}R")
    return "\n".join(satir)


def trend_portfoyu(state: dict, cfg: dict, btc_d: pd.DataFrame) -> str | None:
    """Gunluk trend portfoyu: son kapanan gunluk mumdan sonra bir kez calisir, degisiklik varsa mesaj dondurur."""
    son_gun = str(btc_d["open_time"].iloc[-1])[:10]
    if state.get("trend_son_gun") == son_gun and state.get("trend_ayar") == json.dumps(Z.AYAR, sort_keys=True):
        return None
    G = {}
    for sym in cfg["COINLER"]:
        try:
            g = btc_d if sym == "BTCUSDT" else veri.mumlar_onbellekli(sym, "1d", cfg["VERI_BAS_1D"])
            if len(g) > 100:
                G[sym] = g[["open_time", "close", "volume"]]
        except Exception as exc:
            print(f"trend verisi yok {sym}: {exc}", flush=True)
        time.sleep(cfg["ISTEK_BEKLEME"])
    if len(G) < len(cfg["COINLER"]) * 0.8:
        print("trend portfoyu: veri eksik, atlandi", flush=True)
        return None
    kap, hac = Z.tablolar(G)
    if str(kap.index[-1])[:10] != son_gun:
        return None
    w = Z.hedef_agirlik(kap, hac, top=Z.AYAR["top"], hedef_vol=Z.AYAR["hedef_vol"],
                        max_kaldirac=Z.AYAR["max_kaldirac"], min_gecmis=Z.AYAR["min_gecmis"],
                        min_skor=Z.AYAR["min_skor"], tam_boy=Z.AYAR["tam_boy"])
    olcek = cfg["TREND_OLCEK"]
    hedef = (w.iloc[-1] * olcek).round(4)
    ayar_izi = json.dumps(Z.AYAR, sort_keys=True)
    kural_degisti = "trend_portfoy" in state and state.get("trend_ayar") != ayar_izi
    ilk = "trend_portfoy" not in state or kural_degisti
    eski = {} if ilk else {s_: float(v) for s_, v in (state.get("trend_portfoy") or {}).items()}
    state["trend_ayar"] = ayar_izi
    bant = Z.AYAR["bant"] * olcek
    yeni, al, kapat, degis = {}, [], [], []
    for sym in sorted(set(eski) | set(hedef[hedef > 0].index)):
        h = eski.get(sym, 0.0)
        if sym not in hedef.index or pd.isna(kap[sym].iloc[-1]):
            if h > 0:
                yeni[sym] = h          # verisi alinamadi: pozisyonu oldugu gibi tut
            continue
        t = float(hedef.get(sym, 0.0))
        esik = max(bant, Z.AYAR.get("bant_oran", 0.33) * max(h, t))
        if h == 0 and t > 0:
            yeni[sym] = t; al.append(sym)
        elif h > 0 and t == 0:
            kapat.append(sym)
        elif abs(t - h) > esik:
            yeni[sym] = t; degis.append((sym, h, t))
        elif h > 0:
            yeni[sym] = h
    state["trend_portfoy"] = yeni
    state["trend_son_gun"] = son_gun
    fiyat = kap.iloc[-1]
    toplam = sum(yeni.values())
    if not (al or kapat or degis) and not ilk:
        return None
    baslik = "📈 GÜNLÜK TREND PORTFÖYÜ" + (" — KURAL GÜNCELLENDİ" if kural_degisti else " — BAŞLANGIÇ" if ilk else "") + f" ({son_gun} günlük kapanışı)"
    satir = [baslik, "İkinci sistem: sadece LONG, günler/haftalar sürer, stop yerine çıkışı bot bildirir. "
                     "Yüzdeler toplam sermayenin oranı = pozisyon büyüklüğü (vadelide 1x kaldıraç değeri)."]
    if kural_degisti:
        satir.append(f"Yeni kural: trend skoru en az {Z.AYAR['min_skor']}/9 olan coinde tam pay, altına düşünce kapat "
                     f"(testte 2020+ +%121, eskisi +%80; ortalama ~5 coin). Önceki trend pozisyonlarını bu listeye göre ayarla; "
                     f"listede olmayanları kapat.")
    if ilk:
        satir.append(f"Şu an tutulması gerekenler ({len(yeni)} coin):" if yeni else "Şu an trend portföyünde coin yok (skoru eşiği geçen coin yok).")
        for sym, v in sorted(yeni.items(), key=lambda x: -x[1]):
            satir.append(f"• {sym.replace('USDT', '')}: sermayenin %{100 * v:.2f}'i ({fmt(float(fiyat[sym]))})")
    else:
        for sym in sorted(al, key=lambda x: -yeni[x]):
            satir.append(f"🟢 AL {sym.replace('USDT', '')}: sermayenin %{100 * yeni[sym]:.2f}'i ({fmt(float(fiyat[sym]))})")
        for sym, h, t in sorted(degis, key=lambda x: -(x[2] - x[1])):
            satir.append(f"{'⬆️ ARTIR' if t > h else '⬇️ AZALT'} {sym.replace('USDT', '')}: %{100 * h:.2f} → %{100 * t:.2f}")
        for sym in kapat:
            satir.append(f"🔴 KAPAT {sym.replace('USDT', '')} (trend bitti, {fmt(float(fiyat[sym]))})")
    satir.append(f"Toplam: {len(yeni)} coin, sermayenin %{100 * toplam:.1f}'i. Bir sonraki günlük kapanışa kadar uygulaman yeterli "
                 f"(test 1 gün gecikmeyle yapıldı).")
    return "\n".join(satir)


# ------------------------------------------------------------------------------------
# ANA CALISTIRMA
# ------------------------------------------------------------------------------------
def main():
    cfg = CONFIG
    state = gecis_yap(load_state(cfg))
    ilk_calisma = not state["son_bar"]

    print("BTC verisi aliniyor...", flush=True)
    btc_d = veri.mumlar_onbellekli("BTCUSDT", "1d", cfg["VERI_BAS_1D"])
    btc_4h = veri.mumlar_onbellekli("BTCUSDT", "4h", cfg["VERI_BAS_4H"])
    if len(btc_4h) < 200 or len(btc_d) < 250:
        raise RuntimeError("BTC verisi yetersiz, calistirma iptal (yanlis sinyal riskine karsi).")

    sonuclar: dict[str, k.Sonuc] = {}
    veriler: dict[str, pd.DataFrame] = {}
    mesajlar: list[tuple[pd.Timestamp, str]] = []
    giris_idx: dict[int, int] = {}
    giris_sym: dict[int, str] = {}
    bildirilen_liste = list(state.get("bildirilen", []))
    bildirilen = set(bildirilen_liste)
    hatali = []

    # v6.4 piyasa uyumu: 30 buyuk coinin son 6 mumdaki yukari kirilimlari (short filtresi)
    gen_veri = {}
    for gs in GENISLIK_COINLER:
        try:
            gen_veri[gs] = btc_4h if gs == "BTCUSDT" else veri.mumlar_onbellekli(gs, "4h", cfg["VERI_BAS_4H"])
        except Exception as exc:
            print(f"genislik verisi yok {gs}: {exc}", flush=True)
        time.sleep(cfg["ISTEK_BEKLEME"])
    if len(gen_veri) < len(GENISLIK_COINLER) - 3:
        raise RuntimeError("Genislik (piyasa uyumu) verisi eksik, calistirma iptal.")
    genislik = k.genislik_serisi(gen_veri, GENISLIK_COINLER, k.PARAMS["genislik_bar"], k.PARAMS["resistance_len"])

    onceki_semboller = set(state["son_bar"])
    for sym in cfg["COINLER"]:
        try:
            df = gen_veri[sym] if sym in gen_veri else veri.mumlar_onbellekli(sym, "4h", cfg["VERI_BAS_4H"])
            gd = btc_d if sym == "BTCUSDT" else None   # coin gunlugu sadece "Coin > EMA200" ayarinda gerekir
            if k.PARAMS["long_sart"] in ("Coin > EMA200", "BTC ve coin > EMA200") and sym != "BTCUSDT":
                gd = veri.mumlar_onbellekli(sym, "1d", cfg["VERI_BAS_1D"])
            veriler[sym] = df
            if len(df) < 120:
                print(f"{sym}: yetersiz veri ({len(df)} mum), atlandi")
                continue
            r = k.simule_et(sym, df, gd, btc_d, btc_4h, genislik=genislik)
            sonuclar[sym] = r
        except Exception as exc:
            print(f"{sym} hata: {exc}", flush=True)
            hatali.append(sym)
            continue
        finally:
            if sym not in gen_veri:
                time.sleep(cfg["ISTEK_BEKLEME"])

        son_bar_onceki = state["son_bar"].get(sym)
        if son_bar_onceki is not None:
            esik = pd.Timestamp(son_bar_onceki)
            for o in r.olaylar:
                if o.zaman <= esik:
                    continue
                anahtar = f"{sym}|{o.tur}|{o.yon}|{o.zaman}"
                if anahtar in bildirilen:
                    continue
                metin = None
                if o.tur == "GIRIS":
                    metin = mesaj_giris(sym, o, cfg)
                elif o.tur == "TP1":
                    metin = mesaj_tp1(sym, o, cfg)
                    state["son_stop_bildirimi"][sym] = o.veri["yeni_stop"]
                elif o.tur == "CIKIS":
                    metin = mesaj_cikis(sym, o, cfg)
                    state.setdefault("trade_log", []).append({
                        "zaman": str(o.zaman), "varlik": sym, "yon": YON[o.yon], "sonuc": o.veri["neden"],
                        "sonuc_r": round(float(o.veri["sonuc_r"]), 3), "sistem": "v6"})
                    state["son_stop_bildirimi"].pop(sym, None)
                elif o.tur == "KIRILIM" and cfg["BILDIR_KIRILIM"]:
                    metin = mesaj_kirilim(sym, o)
                elif o.tur in ("SAHTE", "ZAMAN_ASIMI") and cfg["BILDIR_KIRILIM"]:
                    metin = mesaj_iptal(sym, o)
                if metin:
                    if o.tur == "GIRIS":
                        giris_idx[len(mesajlar)] = o.yon
                        giris_sym[len(mesajlar)] = sym
                    mesajlar.append((o.zaman, metin))
                    bildirilen.add(anahtar)
                    bildirilen_liste.append(anahtar)

            # TP1 sonrasi iz suren stop belirgin ilerlediyse bildir
            a = r.acik
            if a and a["tp1_done"]:
                onceki = state["son_stop_bildirimi"].get(sym)
                if onceki is not None and a["yon"] * (a["stop"] - onceki) >= cfg["BILDIR_TRAIL_R"] * a["risk"]:
                    mesajlar.append((r.son_bar, mesaj_trail(sym, a, onceki)))
                    state["son_stop_bildirimi"][sym] = a["stop"]
                elif onceki is None:
                    state["son_stop_bildirimi"][sym] = a["stop"]
        if r.son_bar is not None:
            state["son_bar"][sym] = str(r.son_bar)

    # Guven etiketi: son 24 saatte (6 x 4s mum, bu mum dahil) ayni yonde kac coin giris sinyali verdi
    # (19 Eki 2026 testi, 2020+: 5+ -> isabet ~%73, 8+ -> ~%80, 5'in alti -> ~%53)
    cekirdek = set(CEKIRDEK)
    tum_giris = [(o.zaman, o.yon) for s_, r_ in sonuclar.items() if s_ in cekirdek for o in r_.olaylar if o.tur == "GIRIS"]
    for idx, yon_ in giris_idx.items():
        z_, metin_ = mesajlar[idx]
        n_ = sum(1 for zz, yy in tum_giris if yy == yon_ and z_ - pd.Timedelta(hours=20) <= zz <= z_)
        if giris_sym.get(idx) not in cekirdek:
            n_ += 1                    # cekirdek disi coinin kendi sinyali
        mesajlar[idx] = (z_, guven_etiketi(metin_, n_, yon_))

    simdi_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
    bayat_sinir = simdi_utc - pd.Timedelta(hours=cfg["BAYAT_SAAT"] + 4)
    taze = [m for m in mesajlar if m[0] >= bayat_sinir]
    bayat = [m for m in mesajlar if m[0] < bayat_sinir and not m[1].startswith(("🟡", "⚪", "🔧"))]
    if bayat:
        satirlar = [f"⏪ Bot bir süre çalışamadı; kaçırılan {len(bayat)} olay (sadece bilgi, işlem için geç):"]
        for t, metin in sorted(bayat, key=lambda x: x[0]):
            satirlar.append(f"• {tr_saat(t + pd.Timedelta(hours=4))} — " + metin.split("\n")[0])
        satirlar.append("Güncel açık pozisyonlar akşam özetinde; acil bakmak için TradingView grafiğini aç.")
        send_telegram("\n".join(satirlar))
    # Ayni 4 saatlik mum kapanisindaki tum olaylar TEK mesajda (onem sirasina gore)
    oncelik = {"🟢": 0, "🔴": 0, "✅": 1, "❌": 1, "🟠": 2, "🔧": 3, "🟡": 4, "⚪": 5}
    gruplar: dict = {}
    for t, metin in taze:
        gruplar.setdefault(t, []).append(metin)
    for t in sorted(gruplar):
        liste = sorted(gruplar[t], key=lambda m: oncelik.get(m[:1], 9))
        giris = sum(m.startswith(("🟢", "🔴")) for m in liste)
        kapanis = sum(m.startswith(("✅", "❌")) for m in liste)
        baslik = (f"🕓 4s mum kapanışı {tr_saat(t + pd.Timedelta(hours=4))} — "
                  f"{giris} giriş, {kapanis} kapanış, {len(liste) - giris - kapanis} diğer")
        for simge, yon_ad in (("🟢", "LONG"), ("🔴", "SHORT")):
            n_ = sum(m.startswith(simge) for m in liste)
            if n_ >= 4:
                baslik += (f"\n⚠️ Aynı anda {n_} {yon_ad} sinyali: bunlar aynı piyasa hareketine bağlı, genelde birlikte "
                           f"kazanır ya da birlikte kaybeder. Hepsine girersen toplam risk ≈ {n_} × %{k.PARAMS['hesap_risk']:g} "
                           f"= %{n_ * k.PARAMS['hesap_risk']:g}. (Testte bu toplu sinyaller ortalamada en iyi işlemler; "
                           f"ama en kötü tek gün de böyle bir kümeden geldi: 14 short aynı gün başarısız kırılımla kapandı, −7.2R.)")
        send_telegram(baslik + "\n\n" + "\n\n".join(liste) if len(liste) > 1 else liste[0])

    # BTC durumu
    btc_c = btc_d["close"].to_numpy(float)
    e200 = k.ema(btc_c, 200)[-1]
    e50 = k.ema(btc_c, 50)[-1]
    btc_bilgi = (f"BTC (günlük kapanış {fmt(btc_c[-1])}): EMA50 {'üstünde' if btc_c[-1] > e50 else 'altında'}, "
                 f"EMA200 {'üstünde → long açık' if btc_c[-1] > e200 else 'altında → yeni long yok, sadece short'}")
    if len(genislik):
        gn = int(genislik.iloc[-1])
        btc_bilgi += (f"\nPiyasa uyumu: son 24 saatte {gn} büyük coin (30'dan) yukarı kırılım yaptı → "
                      + ("yeni short açılmaz" if gn > k.PARAMS["genislik_max"] else "short sinyalleri açık"))

    eklenen = [x for x in sonuclar if x not in onceki_semboller]
    if not ilk_calisma and eklenen:
        satir = [f"➕ İzleme listesine {len(eklenen)} coin eklendi (toplam {len(sonuclar)}).",
                 "Seçim geçmiş başarıya göre değil, kurala göre: Binance'te günlük hacmi yüksek (≥ ~2.4M$), "
                 "en az 6 aylık, stablecoin/hisse/altın olmayan coinler. Testte bu grup da iki dönemde kârda "
                 "(işlem başı ~0.10R, ilk 46 coinde ~0.15R).",
                 "Bu coinlerdeki eski sinyaller gönderilmez; bundan sonraki mumlardan itibaren takip edilir.",
                 ", ".join(x.replace("USDT", "") for x in eklenen)]
        acik_y = [(x, sonuclar[x].acik) for x in eklenen if sonuclar[x].acik]
        if acik_y:
            satir.append("Bu coinlerde sisteme göre şu an açık pozisyon var (giriş zamanı geçmiş, sadece bilgi): "
                         + ", ".join(f"{x.replace('USDT', '')} {YON[a['yon']]}" for x, a in acik_y))
        send_telegram("\n".join(satir))
    import hashlib
    parmak = hashlib.md5(json.dumps(k.PARAMS, sort_keys=True).encode()).hexdigest()[:10]
    if not ilk_calisma and state.get("ayar_parmak_izi") != parmak:
        acik = [(s, r.acik) for s, r in sonuclar.items() if r.acik]
        satir = ["⚙️ Sistem güncellendi (v6.6): ince ayar - TP1 0.8R → 0.9R, kırılım tamponu 0.1 → 0.05 ATR, "
                 "başarısız kırılım çıkışı 0.15 → 0.1 ATR, zaman stopu eşiği 0.5R → 0.8R. "
                 "Tüm ayarlar tek tek gözden geçirildi (125 test); bu birleşim üç dönemin üçünde de daha iyi (+5.1R / +5.5R / +1.3R). "
                 "TradingView grafiğiyle aynı ayar.",
                 btc_bilgi]
        if acik:
            satir.append("Açık pozisyonlar (yeni kurallara göre; giriş zamanı geçmiş olabilir, sadece bilgi):")
            for s, a in acik:
                satir.append(f"• {s} {YON[a['yon']]} giriş {fmt(a['giris'])} | stop {fmt(a['stop'])} | "
                             f"TP1 {fmt(a['tp1'])}{' ✓' if a['tp1_done'] else ''} | TP2 {fmt(a['tp2'])} | anlık {a['anlik_r']:+.2f}R")
        else:
            satir.append("Yeni kurallara göre açık pozisyon yok.")
        send_telegram("\n".join(satir))
    state["ayar_parmak_izi"] = parmak

    if ilk_calisma:
        acik = [(s, r.acik) for s, r in sonuclar.items() if r.acik]
        satir = ["🔄 Bot Kirilim69 PRO v6'ya güncellendi (TradingView göstergesiyle aynı mantık).",
                 f"İzlenen: {len(sonuclar)} coin, 4 saatlik, long + short. BIST takibi kapatıldı (v6 sadece kriptoda test edildi).",
                 btc_bilgi]
        if acik:
            satir.append("\nv6'ya göre şu an açık pozisyonlar (bilgi için, giriş zamanı geçmiş olabilir):")
            for s, a in acik:
                satir.append(f"• {s} {YON[a['yon']]} giriş {fmt(a['giris'])} ({tr_saat(pd.Timestamp(a['zaman']) + pd.Timedelta(hours=4))}) | "
                             f"stop {fmt(a['stop'])} | TP1 {fmt(a['tp1'])}{' ✓' if a['tp1_done'] else ''} | TP2 {fmt(a['tp2'])} | "
                             f"anlık {a['anlik_r']:+.2f}R")
        eski = state.get("eski_pozisyonlar") or {}
        if eski:
            satir.append(f"\nEski sistemden açık {len(eski)} pozisyon kapanana kadar eski kurallarla takip edilecek "
                         f"([ESKİ SİSTEM] etiketiyle): " + ", ".join(x.split('] ')[-1] for x in eski))
        satir.append("\nHer 4 saatlik mum kapanışındaki sinyaller tek mesajda toplu gelir; her akşam 21:00'de günlük özet.")
        send_telegram("\n".join(satir))

    if not ilk_calisma and not state.get("duyuru_guven_etiketi"):
        send_telegram("🆕 Yeni: GÜVEN ETİKETİ\n"
                      "Bundan sonra her 🟢/🔴 GİRİŞ mesajının ikinci satırında şu etiketlerden biri olacak:\n"
                      "⭐⭐ ÇOK YÜKSEK GÜVEN — son 24 saatte 8+ coin aynı yönde sinyal verdi (testte isabet ~%80)\n"
                      "⭐ YÜKSEK GÜVEN — 5–7 coin aynı yönde (testte ~%73)\n"
                      "Tekil sinyal — 5'ten az (testte ~%53, kazancı çok düşük): sadece yıldızlıları alıyorsan pas geç.\n"
                      "Sadece yıldızlıları almak testte kârın ~%80'ini korudu, en büyük düşüşü yarıya indirdi; ayda ~3 işlem. "
                      "Yıldızlı sinyaller toplu gelir: o günlerde toplam riske dikkat (ör. 10 işlem × %0.5 = %5).")
        state["duyuru_guven_etiketi"] = True

    eski_pozisyonlari_yonet(state, veriler)

    if cfg["TREND_PORTFOY"]:
        try:
            tm = trend_portfoyu(state, cfg, btc_d)
            if tm:
                send_telegram(tm)
        except Exception as exc:
            print(f"trend portfoyu hata: {exc}", flush=True)

    if cfg["SHORT_RETEST"]:
        try:
            for m in short_retest_sistemi(state, cfg):
                send_telegram(m)
            if state.get("duyuru_short_retest") and not state.get("duyuru_short_retest2"):
                send_telegram(
                    "⚙️ K69 SHORT güncellendi: daha fazla sinyal\n"
                    "Destek test şartı kaldırıldı, coin hacim sınırı 5M$ → 2M$. Son 12 ayda haftada ~1.9 → ~4.3 sinyal.\n"
                    "Etiketler (test, 2020–Eki 2026):\n"
                    "⭐⭐ = destek 3+ kez test edilmiş, coin ≥5M$ → isabet ~%87 (son 12 ay %80)\n"
                    "⭐ = destek 2 kez test edilmiş, coin ≥5M$ → ~%82 (son 12 ay %76)\n"
                    "yıldızsız = diğerleri (destek testi az veya coin sığ) → ~%77 (son 12 ay %72): riski yarıya indir.\n"
                    "Toplam: isabet ~%81.5, son 12 ayda %75. TradingView'daki K69 SHORT Retest göstergesi de aynı kurala güncellendi.")
                state["duyuru_short_retest2"] = True
            if not state.get("duyuru_short_retest") and state.get("short_son_bar"):
                send_telegram(
                    "🆕 Yeni sistem: K69 SHORT (düşük hacimli retest short)\n"
                    "Tüm likit Binance vadeli coinlerinde (günde ≥2M$ hacim) 4 saatlik tarama:\n"
                    "1) Destek (80 veya 160 mumluk dip) hacimli kırılır\n"
                    "2) Fiyat 2–30 mum içinde kırılan seviyeye DÜŞÜK HACİMLE (2 yeşil mum) geri yükselir\n"
                    "3) Seviyenin altında kırmızı kapanan ret mumunda short\n"
                    "Stop: seviyenin 0.8 ATR üstü. Hedef: 0.5R'de tamamını kapat. Zaman stopu 30 mum.\n"
                    "Test (2020–Eki 2026, delist olanlar dahil, maliyet dahil): 822 işlem, isabet %81.5; son 12 ayda %75. "
                    "⭐⭐ = destek 3+ kez test edilmiş (~%87), ⭐ = 2 kez (~%82), yıldızsız ~%77 (riski yarıya indir).\n"
                    "Öneri: işlem başı %0.5 risk (ilk ay %0.25 ile canlıda doğrula), aynı anda en fazla 5 açık short. "
                    "Küçük hedef isabeti yüksek tutan şey; uzatmaya çalışma.\n"
                    "Bu sinyaller 🔻 ile gelir; mevcut v6.6 (🟢/🔴) sinyallerinden ayrıdır. "
                    "Eşikler geçmiş veriye bakılarak seçildi, canlı isabet birkaç puan düşük çıkabilir.")
                state["duyuru_short_retest"] = True
        except Exception as exc:
            print(f"short retest hata: {exc}", flush=True)

    # gunluk ozet
    simdi = datetime.now(timezone.utc)
    bugun = simdi.astimezone(TR).strftime("%Y-%m-%d")
    ozet_zorla = os.environ.get("OZET_ZORLA") == "true"
    if ozet_zorla or (simdi.hour >= cfg["GUNLUK_OZET_SAAT_UTC"] and state.get("son_ozet_gunu") != bugun and not ilk_calisma):
        oz = gunluk_ozet(state, sonuclar, btc_bilgi)
        if cfg["SHORT_RETEST"]:
            oz += "\n" + short_ozet(state)
        send_telegram(oz)
        state["son_ozet_gunu"] = bugun

    if len(hatali) > len(cfg["COINLER"]) // 2:
        send_telegram(f"⚠️ Bot uyarısı: {len(hatali)} coinin verisi alınamadı ({', '.join(hatali[:8])}...). "
                      f"Binance erişim sorunu olabilir; sonraki çalıştırmada tekrar denenecek.")

    state["bildirilen"] = bildirilen_liste[-3000:]
    state["trade_log"] = state.get("trade_log", [])[-1000:]
    state["son_calisma"] = simdi.isoformat(timespec="seconds")
    save_state(state, cfg)
    print(f"\nTarama tamamlandi. Basarili: {len(sonuclar)} | Hatali: {len(hatali)} | Gonderilen mesaj: {len(mesajlar)}")


if __name__ == "__main__":
    if os.environ.get("TEST_MODE") == "true":
        send_telegram("Kirilim69 PRO v6 botu: bu bir TEST mesajıdır. Telegram bağlantısı çalışıyor.")
        sys.exit(0)
    main()
