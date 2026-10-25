"""Telegram ayarini kontrol eder; token degerini EKRANA YAZMAZ, sadece bicimini ve Telegram'in cevabini gosterir."""
import os, re, requests
os.chdir(os.path.dirname(os.path.abspath(__file__)))
raw = open("k69_islem.env", "rb").read()
print("Dosya:", "UTF-8 BOM var" if raw.startswith(b"\xef\xbb\xbf") else "BOM yok")
deg = {}
for satir in raw.decode("utf-8", "replace").splitlines():
    satir = satir.lstrip("﻿")
    if "=" in satir and not satir.strip().startswith("#"):
        k, v = satir.split("=", 1)
        deg[k.strip()] = v
t = deg.get("TELEGRAM_BOT_TOKEN", "")
c = deg.get("TELEGRAM_CHAT_ID", "")
print(f"Token: uzunluk {len(t)}, ':' sayisi {t.count(':')}, bastaki/sondaki bosluk {t != t.strip()}, "
      f"tirnak {chr(34) in t or chr(39) in t}, 'bot' ile basliyor {t.strip().lower().startswith('bot')}, "
      f"garip karakter {[hex(ord(x)) for x in t if ord(x) > 126 or ord(x) < 33][:5]}")
print("Token bicimi dogru mu:", bool(re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,40}", t.strip())))
print(f"Chat ID: uzunluk {len(c)}, sadece rakam (ve basta -) {bool(re.fullmatch(r'-?[0-9]+', c.strip()))}")
temiz = t.strip().strip('"').strip("'")
if temiz.lower().startswith("bot"):
    temiz = temiz[3:]
r = requests.get(f"https://api.telegram.org/bot{temiz}/getMe", timeout=15)
print("Telegram getMe:", r.status_code, r.json().get("result", {}).get("username") if r.ok else r.text[:150])
if r.ok:
    try:
        u = requests.get(f"https://api.telegram.org/bot{temiz}/getUpdates", timeout=15).json().get("result", [])
        ids = {}
        for x in u:
            m = x.get("message") or x.get("channel_post") or x.get("my_chat_member") or {}
            ch = m.get("chat") or {}
            if ch.get("id") is not None:
                ids[ch["id"]] = ch.get("title") or ch.get("first_name") or ch.get("username") or ""
        if ids:
            print("Bota mesaj atan sohbetler (Chat ID):")
            for i, ad in ids.items():
                print(f"   {i}   ({ad})")
        else:
            print("Chat ID bulunamadi: Telegram'da botuna herhangi bir mesaj yaz (or. merhaba), sonra bunu tekrar calistir.")
    except Exception as exc:
        print("getUpdates hatasi:", exc)
    r2 = requests.post(f"https://api.telegram.org/bot{temiz}/sendMessage", data={"chat_id": c.strip(), "text": "K69 Telegram kontrol mesaji"}, timeout=15)
    print("Mesaj gonderimi:", r2.status_code, "OK" if r2.ok else r2.text[:200])
input("Kapatmak icin Enter'a bas...")
