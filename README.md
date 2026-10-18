# Kirilim69 PRO v6 — Telegram izleme botu

TradingView'daki **Kirilim69 PRO** göstergesinin aynısını 102 kripto parada (Binance, 4 saatlik) izler ve sinyalleri Telegram'a gönderir. **Gerçek işlem açmaz.**

## Dosyalar
| Dosya | Görev |
|---|---|
| `kirilim_v6.py` | Göstergenin karar mantığı (elekler, giriş, stop/TP, yönetim). Bot ve backtest bunu kullanır. |
| `genel_izleme_bulut.py` | Bot. Saatte bir çalışır, yeni kapanan mumlardaki olayları gönderir, akşam 21:00'de özet atar. |
| `v6_backtest.py` | Aylık doğrulama: aynı kodla geçmiş işlemleri hesaplar, Telegram'a rapor atar. |
| `coin_listesi.py` | İzlenen coinler. Eklemek/çıkarmak için yalnızca bu listeyi düzenle. |
| `veri.py` | Binance mum verisi (önbellekli). |
| `izleme_state.json` | Botun hafızası (bot kendisi günceller, elle düzenleme). |

## Telegram mesajları
- 🟢/🔴 **GİRİŞ**: giriş, stop, TP1 (%90 kapat), TP2 (kalan %10), önerilen pozisyon büyüklüğü (%1 risk)
- 🟠 **TP1**: %90 kapat, stop giriş + 0.1R
- 🔧 **STOP GÜNCELLE**: TP1 sonrası iz süren stop belirgin ilerlediğinde
- ✅/❌ **KAPANDI**: TP2, stop, zaman stopu — sonuç R (komisyon dahil)
- 🟡 **KIRILIM** / ⚪ **iptal**: retest bekleyen kırılım ön uyarısı (`BILDIR_KIRILIM` ile kapatılabilir)
- 📊 **Günlük özet** (21:00): açık pozisyonlar, BTC durumu, son 30 gün

## Doğrulama (Ekim 2026)
Python sürümü TradingView göstergesiyle karşılaştırıldı (46 coin, Temmuz 2025 sonrası, komisyon dahil):
TradingView 179 işlem / %63.7 / +18.26R — bot 179 işlem / %63.7 / +18.24R.

## v6.1 ayarları (Ekim 2026 araştırması)
GitHub Actions'ta 59 tekil ayar, 12 kombinasyon, 4 zaman dilimi ve listede olmayan 70 coin test edildi (eğitim: Tem 2024–Haz 2025, test: Tem 2025 sonrası).
- **Giriş: kırılım mumunun kapanışında** (retest beklemek yerine). 46 coin: eğitim +31.6R → +45.6R, test +18.2R → +35.2R. 116 coin: +49.9R → +67.3R / +34.3R → +48.6R.
- **4 saatlik** en iyisi (6s zayıf; 8s ve 12s test döneminde zararda).
- Pozisyon tavanı (aynı yönde en fazla 5–8) kazancı ciddi düşürdüğü için uygulanmadı.
- 46 coinde maksimum düşüş ~13R → işlem başı risk **%0.5** önerilir (~%6.5 hesap düşüşü).
- Long tarafı son dönemde zayıf, short tarafı güçlü; bot ikisini de bildirir.

## Kalabalık uyarısı (Ekim 2026 araştırması)
626 işlemde girişteki hacim ivmesi, taker alım/satım oranı, funding, open interest değişimi ve long/short oranları incelendi (Binance arşivi). Tutarlı çıkan tek etken: **büyük oyuncuların (top trader) pozisyon oranı** girişin yönüne yığılmışsa (L/S > 1.69, short'ta S/L > 1.69) işlem başı getiri dört grubun dördünde düşük (test döneminde negatif). Filtre olarak eklemek eğitim döneminde kazancı düşürdüğü için **filtre değil, risk uyarısı**: giriş mesajında "riski yarıya indir" olarak gösterilir. Veri TradingView'da olmadığı için sadece botta.

## v6.2: Başarısız kırılımda erken çıkış (Ekim 2026)
TP1 alınmadan, girişten sonraki ilk 3 mumda 4s kapanış kırılan seviyenin 0.3 ATR gerisine dönerse stop beklenmeden kapanışta çıkılır.
116 coin: eğitim +64.5R → +63.8R, test +42.0R → +52.1R; maksimum düşüş 5.1R → 3.9R ve 20.1R → 14.5R. İsabet ~4–5 puan düşer (küçük kayıplar).
Ayrıca test edilip **eklenmeyenler**: limit emirle giriş, 1 saatlikte giriş, EMA21 geri çekilme sinyali, kovalama filtreleri, klasik formasyonlar.

## v6.3: yeni giriş tarzına göre yeniden kalibrasyon (Ekim 2026)
Eski 60 ayar, kırılım kapanışında giriş yapan v6.2 üzerinde yeniden tarandı; iki dönemde de iyileştiren üç ayar 64+25 kombinasyonluk ızgarada birlikte doğrulandı (64 kombinasyonun 58'i iki dönemde de iyi):
- **TP1'de %90 kapat** (eski %70) — iz süren kalan pozisyon kazanç katmıyordu
- **Başarısız kırılım çıkışı 0.15 ATR** (eski 0.3)
- **Maksimum stop 3.5 ATR** (eski 3.0)
116 coin: eğitim +52.0R → +57.8R, test +44.7R → +54.2R; en kötü düşüş 14.3R → 12.5R. Hem eski 46 coinde hem yeni 70 coinde ayrı ayrı iyileşiyor.
Test edilip **eklenmeyenler**: göreli güç (BTC'ye göre), başarısız kırılım sonrası yeniden giriş, coin bazlı sicil, giriş saati / haftanın günü, direnç penceresi 30–500 (80 en iyi), long için BTC EMA alternatifleri, üst direnç mesafesi, kırılan seviyenin yaşı.

## v6.4: Piyasa uyumu filtresi (Ekim 2026)
Piyasa genişliği araştırması: bir short sinyali geldiğinde, aynı anda başka coinler yukarı kırılım yapıyorsa short'lar belirgin şekilde kötü sonuçlanıyor (piyasa tek yönlü düşmüyor, short sıkışması riski).
Kural: `GENISLIK_COINLER`'deki 30 büyük coinden herhangi biri son 6 mumda (24 saat) 80 mumluk tepesinin üstünde kapattıysa **yeni short açılmaz**. Long'lar etkilenmez.
116 coin: eğitim +60.3R → +63.4R, test +53.1R → +65.7R; test isabeti %55.9 → %61.2. 20 / 30 / 40 / 116 coinlik sayım evrenlerinin hepsinde ve 3 / 6 / 9 mumluk pencerelerde iki dönemde de iyileşiyor; 5 yarıyılın 4'ünde daha iyi.
"En fazla 1 coin" gibi gevşek eşikler iyileştirmiyor: kural "hiç ters kırılım yok" olarak çalışıyor.
Ayrıca test edilip eklenmeyenler: ortalamaya dönüş sistemi (48 varyasyon, hepsi zararda), momentum rotasyonu (tutarsız, %35–55 düşüş), dinamik RSI, z-skor, verimlilik oranı, choppiness, FVG, BTC korelasyonu.

## Seçici mod (18 Ekim 2026)
Hacim eşiği 2x → **2.5x** (bot ve TradingView aynı). 116 coin, Tem 2024 – Eki 2026: ayda ~21 → ~13 sinyal, isabet %63.8 → %69.1, işlem başı 0.24R → 0.31R, toplam +135R → +113R, en kötü düşüş 15.3R → 13.0R; Mar–Eki 2026: +7.1R → +11.9R.
Ayrıca 13 parametreli ortak optimizasyon (400 kombinasyon, arama / seçim / son sınav bölmeli) v6.4'ü geçen bir kombinasyon bulamadı; ilk iki dönemde en iyi görünenler son sınavda −8 ile −22R.

## Liste genişletme (Ekim 2026)
Binance'teki ~615 USDT paritesi hacim sırasına göre katmanlara ayrılıp v6.3 ile test edildi. İlk ~70 (46 dışı) katman iki dönemde de kârlı; daha düşük hacimli katmanlarda test kazancı sıfıra yaklaşıyor (ve kayma maliyeti artıyor). Bu yüzden **kurala göre** 56 coin eklendi (hacim ≥ ~2.4M$, ≥ 6 ay geçmiş, stablecoin / tokenize hisse / altın hariç), geçmiş başarıya göre seçim yapılmadı (coin bazlı başarı dönemden döneme taşınmıyor, korelasyon ~0).
102 coin: eğitim +59.2R, test +52.9R (46 coin: +46.7R / +33.1R).

## Elle çalıştırma
GitHub → Actions → *Genel Izleme Botu* → *Run workflow* (`test_mesaji` = true yalnızca Telegram bağlantısını dener).
