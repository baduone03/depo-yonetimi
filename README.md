# Warehouse Intelligence & Slotting Optimizer

Depo operasyonları için yerel çalışan bir karar destek uygulaması (MVP). Geçmiş sipariş hareketlerini analiz
eder, ürünlerin mevcut lokasyonlarını değerlendirir, fiziksel kısıtlara uyan alternatif yerleşimler önerir ve
**aynı siparişler üzerinde** mevcut ve önerilen yerleşimin toplama mesafesini karşılaştırır.

> **Önemli:** Uygulamanın ürettiği mesafe, süre ve maliyet değerleri bir depo modeli üzerinde yapılan
> **simülasyon/tahmin** sonuçlarıdır; ölçülmüş operasyon verisi değildir. Demo verisi **sentetiktir**.
> Uygulama hiçbir stok hareketi yapmaz, hiçbir WMS'e veri yazmaz ve dosyalarınızı dışarı göndermez.

## Kurulum

Python 3.11+ gerekir (3.13 ile test edildi).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Tarayıcıda `http://localhost:8501` açılır. Testler:

```bash
python -m pytest
```

## Streamlit Community Cloud'a yükleme (tarayıcıdan, terminal gerekmez)

1. https://share.streamlit.io adresine GitHub hesabıyla giriş yapın ve Streamlit'e bu repoya erişim izni verin.
2. **Create app → Deploy a public app from GitHub** seçin.
3. Repository: `baduone03/depo-yonetimi`, Branch: `main`, Main file path: `app.py`.
4. *Advanced settings* içinde Python sürümü olarak 3.12 seçin ve **Deploy**'a basın.

Bağımlılıklar `requirements.txt` dosyasından otomatik kurulur. Not: Cloud'a yüklenen dosyalar Streamlit'in
sunucularında işlenir; "veriler dışarı gönderilmez" garantisi yalnızca yerel çalıştırma için geçerlidir. Gerçek
müşteri verisini Cloud sürümüne yüklemeden önce bunu değerlendirin.

## Hızlı başlangıç (demo modu)

1. **Veri Yükleme ve Veri Kalitesi** sayfasında **Sentetik demo verisini yükle**'ye tıklayın.
2. Demo: 80 SKU, 280 lokasyon, 8 koridor (2 seviyeli raf, palet koridoru, soğuk oda), 400 sipariş,
   iade/iptal satırları, sabit ve kullanılamaz lokasyonlar. Sabit seed (`42`) → her çalıştırmada aynı sonuç.
3. Tüm sayfalar demo verisiyle uçtan uca çalışır; her ilgili ekranda "Sentetik demo verisi" uyarısı görünür.

Demo verisinde başlangıç yerleşimi **rastgeledir**; bu yüzden demo iyileşme yüzdeleri (≈%24–28) gerçek bir
depoda beklenecek değeri göstermez.

## Gerçek depo verisi için gereken dosyalar

CSV (`,` veya `;` ayraçlı, UTF-8/Windows-1254) ya da XLSX. Şablonlar `templates/` dizininde ve uygulamada
**Veri sözlüğü ve şablonlar** sekmesinde. Tüm tablolar tek bir Excel çalışma kitabında (sayfa adı = tablo adı)
da yüklenebilir.

| Tablo | Zorunlu kolonlar | Opsiyonel kolonlar |
|---|---|---|
| `products` | sku, length_m, width_m, height_m, weight_kg | product_name, stackable, product_family, storage_requirements, handling_type |
| `order_lines` | order_id, order_date, sku, quantity | movement_type (outbound/çıkış, return/iade, cancel/iptal) |
| `locations` | location_id, aisle_id, x, y | zone, z, location_type, max_weight_kg, max_volume_m3, max_length_m, max_width_m, max_height_m, is_pickable, is_available, is_fixed, storage_class |
| `inventory` | sku, location_id, current_quantity | — |
| `aisles` (opsiyonel geometri) | aisle_id, x_center, y_start, y_end | — |

- Boyut birimi m/cm/mm, ağırlık birimi kg/g/t olarak seçilebilir; içeride metre ve kilogram kullanılır.
  Koordinatlar her zaman metredir.
- Stok seviyesi geçmiş çıkışlardan türetilmez; `inventory` ayrıca sağlanmalıdır. Bir SKU birden çok
  lokasyonda olabilir.
- `aisles` yoksa koridor orta hatları lokasyon koordinatlarından türetilir ve **yaklaşık geometri** olarak
  işaretlenir. Sevkiyat noktası Ayarlar'dan girilir; girilmezse varsayılan konum kullanılır ve bu belirtilir.
- Kapasite bilgisi eksik lokasyonlar **hedef lokasyon olarak kullanılmaz** (güvenli varsayılan).

## Sayfalar

| Sayfa | İçerik |
|---|---|
| Genel Bakış | SKU, sipariş, lokasyon sayıları; ABC dağılımı; taşınması önerilen SKU; mevcut/önerilen mesafe; zaman farkı; iyileşme %. Hesaplanamayan değerler "Hesaplanamadı / Veri gerekli" gösterilir |
| Veri Yükleme ve Veri Kalitesi | Yükleme, birim seçimi, satır/alan/açıklama bazında doğrulama raporu, veri sözlüğü, şablonlar |
| ABC ve Hareket Analizi | Metrik ve eşik seçimi, Pareto eğrisi, ABC dağılımı, hareket sıklığı, SKU tablosu |
| Depo Yerleşim Haritası | Ölçekli 2D harita: koridorlar, lokasyonlar, sevkiyat, ABC/doluluk renkleri, mevcut ↔ önerilen geçişi, taşıma okları, tıklanınca lokasyon detayı |
| Yerleşim Optimizasyonu | İki yöntemin parametreleri ve aynı metriklerle karşılaştırması, taşınamaz/atanamayan SKU'lar |
| Rota ve Mesafe Analizi | Lokasyon erişim mesafeleri, ulaşılamayan lokasyonlar, sipariş bazında mevcut/önerilen rota çizimi |
| Önce / Sonra Simülasyonu | Toplam/ortalama/medyan mesafe, durak, süre, iyileşme; sipariş bazında tablo; projeksiyon |
| Taşıma Planı | Uygulama sırasıyla aksiyon listesi, gerekçe, bağımsız kısıt kontrolü; CSV/XLSX |
| Raporlar | 11 rapor, her biri CSV ve XLSX; tümü tek çalışma kitabında |
| Ayarlar | Mesafe modeli, sevkiyat noktası, tüm parametreler (YAML) |

## Yöntem

**ABC.** Metrik: sipariş satırı sayısı (varsayılan), toplam çıkış miktarı veya hareketli gün sayısı. Dönem:
son çıkış tarihinden geriye 90 gün (veri kısaysa uyarılır). SKU'lar metrik azalan, eşitlikte SKU kodu artan
sıralanır. Kendisinden önceki kümülatif payı < %80 olan A, < %95 olan B, diğerleri C; hareketi olmayan SKU C.
İade ve iptaller dahil edilmez.

**Mesafe modeli.** Paralel koridorlu depo: her koridor bir yürüme hattı, ön ve arka ara koridorlar uçları
bağlar, lokasyona koridordaki erişim noktasından ulaşılır. NetworkX grafı + Dijkstra. Raf içi yanal uzanma ve
dikey seviye (z) yürüme mesafesine eklenmez. Koridor ağı kurulamıyorsa **Manhattan modu yalnızca tahmin**
olarak sunulur.

**Rota.** Tek toplayıcı, sipariş başına tek tur, sevkiyat → duraklar → sevkiyat. En yakın komşu + 2-opt
(sezgisel). Aynı lokasyondaki ürünler tek durak.

**Yerleşim (slotting).** Taşıma bütçesi altında açgözlü iyileştirme. Her adımda en iyi eylem seçilir:
(1) SKU'yu boş bir lokasyona taşı veya (2) hedefteki SKU'yu boş bir lokasyona taşıyıp yer aç ve SKU'yu oraya
taşı (2 hareket). Her SKU en fazla bir kez taşınır ve her taşıma yapıldığı anda boş bir lokasyona gider, bu
yüzden plan tampon lokasyon olmadan sırayla uygulanabilir.

- *Yöntem A — sınıf tabanlı:* uygun lokasyonlar sevkiyata uzaklığa göre A/B/C bölgelerine ayrılır;
  puan = sınıf ağırlığı × mesafe + bölge uyumsuzluk cezası.
- *Yöntem B — hibrit:* puan = sipariş sıklığı × 2 × mesafe + yükseklik cezası + (opsiyonel) ürün ailesi
  yakınlığı + hacim uyumu; bir taşıma, dönem boyunca beklenen kazanç taşıma eşiğini (varsayılan 30 m) aşarsa
  önerilir.

Zorunlu kısıtlar: birim boyutu (yatay döndürme serbest), ağırlık ve hacim kapasitesi, geometrik istif
(istiflenemeyen ürün tek katman), kullanılabilirlik, toplanabilirlik, sabit lokasyon, tek SKU/lokasyon,
depolama koşulu, elleçleme–lokasyon tipi uyumu. Her taşıma motordan bağımsız olarak yeniden doğrulanır.
**Puanlama küresel optimumu garanti etmez; çıktı "önerilen yerleşim"dir.**

**Simülasyon.** İyileşme % = (mevcut − önerilen) / mevcut × 100; mevcut 0 ise tanımsız. Negatif iyileşme
gizlenmez. Süre = mesafe / yürüme hızı + durak × toplama süresi (toplama süresi girilmezse yalnızca yürüme).
Projeksiyon ve maliyet ancak gün sayısı ve saatlik maliyet girildiğinde hesaplanır ve "tahmini" etiketlidir.

## Proje yapısı

```
app.py                      Streamlit giriş noktası (yalnızca sayfa yönlendirme)
config/default_settings.yaml
src/warehouse_optimizer/
  data/          schemas, loaders (CSV/XLSX), validators, demo_generator
  analytics/     movement_analysis, abc_analysis
  layout/        warehouse_model (geometri), visualization (Plotly)
  optimization/  constraints, scoring, slotting_engine
  routing/       warehouse_graph (NetworkX / Manhattan), picking_routes (NN + 2-opt)
  simulation/    comparison (önce/sonra)
  reporting/     exports (CSV/XLSX + metadata), report_builder
  ui/            10 sayfa + ortak yardımcılar
  pipeline.py    UI'dan bağımsız uçtan uca akış
  settings.py
templates/       örnek CSV şablonları
docs/REFERENCE_REPOSITORY_REVIEW.md
tests/           pytest (veri doğrulama, ABC, kısıtlar, slotting, rota, simülasyon, dışa aktarma, UI)
```

## Bilinen sınırlamalar

- Yerleşim yöntemleri sezgiseldir; optimum garanti edilmez. Her SKU en fazla bir kez taşınır; döngüsel
  takaslar (A↔B) tampon lokasyon gerektirdiği için önerilmez.
- Stok bölme politikası: birden çok toplama lokasyonundaki SKU'lar taşınmaz; taşınan SKU tüm miktarıyla taşınır.
  Rezerv → toplama yüzü ikmali modellenmez.
- Depo modeli paralel koridor + ön/arka ara koridor varsayar; orta ara koridor, tek yönlü koridor, balık
  kılçığı gibi düzenler ve engeller modellenmez. Dikey hareket ve raf içi uzanma mesafeye dahil değildir.
- Rota: tek toplayıcı, sipariş başına tek tur; sipariş gruplama (batching), dalga toplama, araç kapasitesi yok.
- Simülasyon geçmiş siparişleri tekrar oynatır; gelecekteki talep değişimi, toplayıcı sıkışması, ikmal ve
  taşıma işçiliği hesaba katılmaz.
- Hibrit puan büyük veri setlerinde S×L matrisiyle çalışır (bellek ≈ SKU × uygun lokasyon). 220 SKU / 2 225
  sipariş ile iki yöntem + simülasyon ≈ 5 sn sürdü; on binlerce lokasyonda bölge/koridor bazlı ön filtre gerekir.
- Kullanıcı hesabı, kalıcı veri saklama ve WMS entegrasyonu yoktur (bilinçli olarak).

## Sonraki adımlar (öneri)

1. **Sipariş gruplama ve dalga toplama** (batch picking) ile çoklu sipariş turları; S-shape / largest-gap rota
   politikalarıyla karşılaştırma.
2. **Takas döngüleri ve ikmal modeli:** tampon lokasyonla A↔B takasları, rezerv → toplama yüzü ikmal maliyeti,
   taşıma işçiliğinin plana dahil edilmesi.
3. **Gerçek ölçümle kalibrasyon:** WMS toplama zaman damgalarından yürüme hızı ve durak süresinin tahmini;
   simülasyonun gerçek turlarla doğrulanması; daha esnek geometri (orta ara koridor, engeller).
