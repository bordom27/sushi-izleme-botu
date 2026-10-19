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
- 🟢/🔴 **GİRİŞ**: giriş, stop, TP1 (%90 kapat), TP2 (kalan %10), önerilen pozisyon büyüklüğü (işlem başı %0.5 risk)
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

## İkinci sistem: günlük trend portföyü (19 Ekim 2026)
`zarattini.py` — Zarattini, Pagani, Barbon (2025) "Catching Crypto Trends" yaklaşımı, sadece LONG, günlük grafik. Her coin için 9 bakış süresinde (5–360 gün) kapanış kırılımı + kanal ortası iz süren stop; sinyal = trendde olan sürelerin oranı; boyut = %25 hedef oynaklık / coinin oynaklığı (en fazla 2 kat), en likit 20 coin, her biri sermayenin 1/20'si üzerinden.
Bot her günlük kapanıştan sonra (03:07 TR) hedefleri hesaplar; değişiklik varsa tek mesaj: 🟢 AL / ⬆️ ARTIR / ⬇️ AZALT / 🔴 KAPAT, yüzdeler toplam sermayenin oranı. Küçük değişiklikte işlem yok (fark sermayenin %1'inden ve mevcut payın %33'ünden küçükse). 21:00 özetinde portföy satırı var.
Test (2020+, 1 gün gecikme + bu bant, %0.1 komisyon): toplam +%80, Sharpe 1.17, max düşüş %9; ortalama 12–13 coin, sermayenin ~%8'i (en fazla ~%33); günlerin ~%58'inde değişiklik. v6.6 ile korelasyon ~0. `TREND_OLCEK` (varsayılan 1.0) v6.6'nın %0.5 riskiyle eşit oynaklık demek; ikisini birlikte büyütmek için ikisini aynı oranda artır.
**Kural (19 Eki 2026): skor ≥ 5/9 ise tam pay, altına düşünce kapat.** Skor eşikleri testi (2020+, gecikme + bant): orantılı skor≥1 +%80 / Sharpe 1.17 / düşüş %9.2; skor≥4 orantılı +%85 / 1.26 / %7.1; **skor≥5 tam pay +%121 / 1.26 / %9.9** (aynı ortalama sermaye ~%8, ortalama ~5 coin, 8 dönemin 7'sinde daha iyi); skor≥3 tam pay +%158 ama düşüş %14.5.
Short tarafı test edildi, eklenmedi: günlük trendin aynası (düşüş kırılımı + kanal ortası stop) 2020+ toplam −%16, Sharpe −0.32, düşüş %24 (sadece 2022'de kârlı); long + short birlikte Sharpe 0.85 (sadece long 1.17). 4 saatlik sistemi sadece short yapmak da kötü: Sharpe 1.48 → 1.16 (long'lar short'ların zayıf olduğu 2020 ve 2024'te kazandırıyor).

## Büyük örneklem: 2020'den bugüne (19 Ekim 2026)
v6.6, 2020 başından bugüne (6.8 yıl, 750 işlem): toplam +153.7R, isabet %61, en kötü düşüş 14.4R. Yıllık: 2020 +12.1R, 2021 +13.9R, 2022 +3.7R, 2023 −0.9R, 2024 ilk yarı +5.1R, A +50.3R, B +63.2R, C +6.5R.
Ayarlar 2024 sonrası veriyle geliştirildiği için 2020–2024 örneklem dışı sayılır; orada işlem başı ~0.09R (A/B'de 0.34R) — gerçekçi beklenti daha düşük. Batan coinler veride yok (hafif iyimser).
Reddedilen fikirlerin hiçbiri her yıl iyileştirmiyor (RSI üst sınırı yok: toplam +27R ama 2021 ve son dönem kötü; BTC filtreleri yok: +18R ama 2021, 2024, son dönem kötü).
Zarattini günlük trend sistemi bu dönemde Sharpe 1.28, v6.6 ile korelasyon 0.01; eşit oynaklıkta ikisi birlikte yıllık ~%23, Sharpe 1.94 (v6.6 tek başına %0.5 riskte ~%12, 1.48).

## Büyük adım araştırması (19 Ekim 2026)
- **Teşhis (Mar–Eki 2026 zayıflığı):** sinyal sayısı ayda ~7'ye düştü (önceki dönemler 12 ve 23). Kâr motoru short tarafı (işlem başı 0.44 / 0.39 / 0.27R); long tarafı her dönemde zayıf (0.24 / 0.10 / 0.02R). Son dönemde BTC çoğunlukla yükselişte olduğu için short fırsatı az çıktı; sistem bozulmadı, piyasa rejimi değişti.
- **Başka zaman dilimleri** (1s, 2s, 6s, 8s, 12s, 1G; olduğu gibi ve takvime ölçekli): hiçbiri 4s'i geçmiyor. 1s/2s zararda, 6s/8s/12s son dönemde negatif.
- **Zarattini tarzı günlük trend sistemi** (Donchian topluluğu, kanal ortası stop, vol hedefli): tek başına zayıf (Sharpe ~0.8, 2. dönem düz), 4s sistemle korelasyon ~0. Yarım ağırlıkla eklemek Sharpe'ı 2.24 → 2.35, son dönemi %3.6 → %6.5 yapıyor; küçük katkı, şimdilik eklenmedi.
- **Toplu sinyaller:** aynı mumda ≥2 aynı yön sinyal en iyi işlemler (8+ kümede işlem başı 0.52R); tekil sinyaller zayıf (0.10R) ama yine kârlı, elemek veya küçültmek sonucu iyileştirmiyor. En kötü gün de bir kümeden: 25 Oca 2026'da açılan 14 short ertesi gün başarısız kırılımla kapandı (−7.2R). Bot artık aynı mumda ≥4 aynı yön sinyalde toplam risk uyarısı veriyor.
- **Risk boyutu** (gerçekçi sermaye eğrisi, eşzamanlı pozisyonlar, bileşik; kâr/zarar çıkışta): %0.5 → yıllık ~%29, max düşüş ~%4; %1 → ~%63, ~%8, en kötü gün ~%−7.5; %1.5 → ~%104, ~%12. Aynı anda 27'ye kadar açık işlem olabiliyor (%0.5 riskte toplam pozisyon sermayenin 2.3 katına çıkabiliyor). Geçmiş test; gerçek işlemde kayma ve dolum farkı sonuçları düşürür.

## v6.6: İnce ayar (19 Ekim 2026)
Tüm ayarlar tek tek gözden geçirildi (125 test, 116 coin, üç dönem). Birleşim: TP1 0.8R → **0.9R**, kırılım tamponu 0.1 → **0.05 ATR**, başarısız kırılım çıkışı 0.15 → **0.1 ATR**, zaman stopu eşiği 0.5R → **0.8R**. Üç dönem: +5.1R / +5.5R / +1.3R (A 44.8 → 49.9R, B 56.4 → 61.9R, C 5.2 → 6.6R); işlem ~%5 fazla, isabet aynı.
Etkisiz çıkanlar (sonucu hiç değiştirmiyor; hacim / ADX / EMA şartları aynı işlemleri zaten eliyor): 4s MACD ve ayarları, panik filtresi, stop sonrası bekleme, RSI alt sınırı.
Kötüleştirenler: hacim filtresini kapatmak (C −25R), short genişlik filtresini kapatmak, EMA'dan uzaklık / mum boyu sınırını daraltmak veya genişletmek, hacim çarpanı 2.0 / 3.0, günlük/haftalık MACD, günlük ana trend, seviye test sayısı, taban genişliği, ATR% sınırı, sıkışma (BB / TTM squeeze), Zarattini / Turtle çıkışları.
Not: RSI üst sınırını (70) kaldırmak 2. dönemde +27R ama son dönemde −7.6R; eklenmedi.

## v6.5: Fib giriş filtresi kaldırıldı (18 Ekim 2026)
Fib 0.618 yapı filtresi kapalı (`use_fib=False`); fib tabanlı TP1/TP2 hedefleri aynen duruyor. Seçici mod üzerinde, üç dönem: +1.4R / +5.6R / +0.7R, işlem ~%9 fazla, isabet ve düşüş aynı.
Fib yerine denenip eklenmeyenler: ölçülü hareket hedefi (20/40/80 mum; 2. dönemde +17–20R ama diğer iki dönemde kötü), sabit R hedefleri, direnç çakışması (büyük fib / 30–60 günlük zirve / eski pivot; sinyal azaltıyor, kaliteyi artırmıyor).

## Seçici mod (18 Ekim 2026)
Hacim eşiği 2x → **2.5x** (bot ve TradingView aynı). 116 coin, Tem 2024 – Eki 2026: ayda ~21 → ~13 sinyal, isabet %63.8 → %69.1, işlem başı 0.24R → 0.31R, toplam +135R → +113R, en kötü düşüş 15.3R → 13.0R; Mar–Eki 2026: +7.1R → +11.9R.
Ayrıca 13 parametreli ortak optimizasyon (400 kombinasyon, arama / seçim / son sınav bölmeli) v6.4'ü geçen bir kombinasyon bulamadı; ilk iki dönemde en iyi görünenler son sınavda −8 ile −22R.

## Liste genişletme (Ekim 2026)
Binance'teki ~615 USDT paritesi hacim sırasına göre katmanlara ayrılıp v6.3 ile test edildi. İlk ~70 (46 dışı) katman iki dönemde de kârlı; daha düşük hacimli katmanlarda test kazancı sıfıra yaklaşıyor (ve kayma maliyeti artıyor). Bu yüzden **kurala göre** 56 coin eklendi (hacim ≥ ~2.4M$, ≥ 6 ay geçmiş, stablecoin / tokenize hisse / altın hariç), geçmiş başarıya göre seçim yapılmadı (coin bazlı başarı dönemden döneme taşınmıyor, korelasyon ~0).
102 coin: eğitim +59.2R, test +52.9R (46 coin: +46.7R / +33.1R).

## Elle çalıştırma
GitHub → Actions → *Genel Izleme Botu* → *Run workflow* (`test_mesaji` = true yalnızca Telegram bağlantısını dener).
