# Referans Repository İncelemesi

**Tarih:** 2026-10-29 · **Yöntem:** Beş reponun hepsi `git clone --depth 1` ile proje dışındaki geçici bir dizine
klonlandı ve kaynak kodu okundu. Testi olan iki repoda (ware-viz, WMS-OptLab) testler yerel olarak çalıştırıldı.
Hiçbir referans projeden kod kopyalanmadı; bu projedeki tüm kod bağımsız olarak yazıldı. Aşağıdaki
değerlendirmeler, incelenen commit'lere aittir.

## Özet tablo

| Repo (commit) | Lisans | Testler | Kullanılan fikirler | Kod yeniden kullanımı |
|---|---|---|---|---|
| solongo5/warehouse-slotting-dashboard (`fac746b`) | **Lisans dosyası yok** | Yok | ABC + hız → bölge eşlemesi, "yanlış yerleşmiş SKU" kavramı, yönetici dashboard'u | Yok (lisans yok) |
| TerexSpace/whse-optimize-toolkit — WMS-OptLab (`3f36663`) | MIT | 9 test, 9 geçti | Graf tabanlı en kısa yol, deterministik sıralama, senaryo karşılaştırması | Yok (bağımsız uygulama) |
| 8uhr-ai/ware-viz (`b058ee3`) | MIT (yalnızca `pyproject.toml`'da beyan; lisans metni dosyası yok) | 7 test, 7 geçti | ABC/hacim renklendirmeli 2D üst görünüm fikri | Yok (kendi Plotly modülü) |
| Vikas-Jakhar/warehouse-operations-optimization (`f33eaf6`) | **Lisans dosyası yok** (README'de "MIT — eğitim/portföy amaçlı" ifadesi) | Yok | Sentetikten dashboard'a uçtan uca akış, Zipf talep dağılımı | Yok (lisans belirsiz) |
| vinit714/Optimizing-Warehouse-Efficiency-via-Python-Based-Order-Batching (`cde0ee5`) | MIT | Yok | Tek toplayıcı rota problemi, dalga/küme toplama (sonraki aşama) | Yok |

---

## 1. warehouse-slotting-dashboard

- **Yapı / giriş noktası:** Tek dosya `app.py` (573 satır) + `lane.csv`. `streamlit run app.py`.
- **README ↔ kod:** README Azure SQL'de ABC sınıflandırması ve hareket hızı hesaplandığını anlatıyor; **bu SQL
  repoda yok**. `app.py`, ABC ve hız sınıflarını önceden hesaplanmış olarak `lane.csv`'den okuyor
  (`abc_class`, `speed_class`, `zone` kolonları). `requirements.txt` içinde `pyodbc` var ama kodda import
  edilmiyor. README'deki "haftada 9,8 saat / ~246 $ tasarruf" kodda hesaplanmıyor; doğrulanamaz.
- **Slotting mantığı:** `get_recommended_zone(abc, speed)`: A → Priority, B+Fast → Priority, B → Standard,
  diğerleri → Reserve. "Yanlış yerleşim" = Priority dışındaki A veya Priority içindeki C. Kapasite, boyut,
  ağırlık kısıtı yok; rota yok; hedef lokasyon önerisi bölge seviyesinde.
- **Görselleştirme:** Altair grafikleri + HTML ile çizilen bin haritası.
- **Alınan fikirler:** ABC × hız → bölge mantığı (bizde "Yöntem A — sınıf tabanlı" bölge cezası olarak
  genelleştirildi), "taşınması gereken SKU" listesi, yönetici KPI kartları.
- **Alınmayanlar ve nedeni:** Lisans dosyası olmadığı için kod kullanılamaz. Tek dosyada toplanmış iş mantığı
  yerine test edilebilir modüller yazıldı. Azure SQL bağımlılığı yok; yerel CSV/XLSX.

## 2. WMS-OptLab (whse-optimize-toolkit)

- **Yapı:** `src/wms_optlab/` altında `slotting/`, `routing/`, `batching/`, `layout/`, `scenarios/`,
  `experiments/` (~11 300 satır Python). CLI giriş noktası `wms_optlab.cli:main`. Bağımlılıklar: numpy, pandas,
  networkx, **ortools**, matplotlib, click.
- **README ↔ kod:** README'deki minimal örnek `examples/data/sample_*.csv` dosyalarını okuyor; **bu dizin repoda
  yok** (yalnızca iki notebook var), örnek olduğu gibi çalışmaz.
- **ABC / slotting:** `assign_by_abc_popularity` toplam miktara göre sıralayıp (eşitlikte SKU kodu) depoya en
  yakın lokasyonlara atıyor. **Kapasite, boyut, ağırlık, sabit lokasyon kısıtı yok.** Ayrıca OR-Tools tabanlı
  MILP modeli ve metasezgisel batching modülleri var (araştırma odaklı).
- **Rota:** `create_warehouse_graph` koridor bağlantısı verilmezse **tam bağlı (complete) graf + Manhattan**
  kuruyor; bu, rafların içinden geçişe izin veren bir yaklaşımdır. `find_optimal_tour_tsp` NetworkX yaklaşık
  TSP çözücüsünü kullanıyor ("optimal" adına rağmen yaklaşık). S-shape, largest-gap gibi politikalar var.
- **Testler:** 4 dosya, 9 test; `PYTHONPATH=src` ile 9/9 geçti (ortools kurulmadan).
- **Alınan fikirler:** Koridor ağını NetworkX grafı olarak modelleme ve Dijkstra; deterministik eşitlik
  bozma; senaryo karşılaştırma yaklaşımı.
- **Alınmayanlar ve nedeni:** Paket bağımlılık olarak eklenmedi: OR-Tools ağır bir bağımlılık, slotting
  sezgiseli fiziksel kısıtları kapsamıyor ve tam bağlı graf yürüme mesafesini olduğundan kısa gösterir. Kendi
  koridor grafiğimiz yalnızca koridor ve ara koridor kenarlarından oluşur.

## 3. ware-viz

- **Yapı:** `src/ware_viz/visualizer.py` (~1 200 satır), `WarehouseVisualizer(unit="mm", anchor_point=...)`,
  `plot_top(...)` ve `plot_front(...)`; `engine="plotly"` veya matplotlib.
- **Beklenen şema:** `loc_id, pos_x, pos_y, pos_z, loc_width, loc_depth, loc_height`; parçalar
  `item_id, pkg_len, pkg_width, pkg_depth, pkg_weight, demand, abc_class`; tahsis `loc_id, item_id, alloc_qty`.
- **Bağımlılık:** Plotly motoru kullanılsa bile `matplotlib` import ediliyor. Lisans `pyproject.toml`'da MIT
  olarak beyan edilmiş, ayrı lisans metni dosyası yok.
- **Testler:** 7 test, 7/7 geçti.
- **Karar:** Entegre edilmedi. Kütüphane raf ayak izi ve ön görünüm çiziyor; bizim ihtiyacımız olan koridor
  ağı, sevkiyat noktası, rota çizgisi, mevcut→hedef taşıma okları ve Streamlit tıklama seçimi kapsamında
  değil. Şema dönüşümü + matplotlib bağımlılığı, sağladığı faydadan fazla. Plotly tabanlı kendi modülümüz
  yazıldı (`layout/visualization.py`). Ön (elevation) görünüm fikri sonraki aşama için not edildi.

## 4. warehouse-operations-optimization

- **Yapı:** `main.py`, `app.py`, `src/{data_generator, slotting_optimization, simulation, visualize}.py`.
  Test dizini yok.
- **ABC:** Kümülatif toplama payına göre A ≤ %80, B ≤ %95, C kalan (bizim varsayılan eşiklerle aynı mantık).
- **İyileşme iddiası:** README "~%15–20 mesafe azalması" diyor. Kodda **"mevcut" senaryo rastgele karıştırılmış
  bir yerleşim** (`baseline_slotting` iki bağımsız permütasyon) ve optimize senaryo sınıf/talep sırasıyla en
  yakın lokasyonlara atama. Mesafeler Manhattan. Yani rakam rastgele bir başlangıca göre sentetik bir
  karşılaştırmadır; gerçek, doğrulanmış bir sonuç olarak kabul edilmedi.
- **Lisans:** Lisans dosyası yok; README'deki "eğitim veya portföy amaçlı" ifadesi belirsiz → kod kullanılmadı.
- **Alınan fikirler:** Deterministik sentetik veri → analiz → dashboard akışı; Zipf benzeri talep dağılımı.
  Bizim demo verimizde de başlangıç yerleşimi rastgeledir; bu nedenle demo iyileşme yüzdeleri arayüzde ve
  README'de açıkça "sentetik" olarak işaretlenir.

## 5. Optimizing-Warehouse-Efficiency-via-Python-Based-Order-Batching

- **Yapı:** `app.py` (Streamlit), `utils/routing/{distances,routes}.py`, `utils/batch/*`, `utils/cluster/*`.
  Commit'lenmiş `__pycache__` (cpython-38) dosyaları var; `requirements.txt` 2021 sürümlerine sabitli
  (streamlit 0.77, pandas 1.3.4) → güncel Python'da kurulumu zor. Test yok.
- **Rota:** `distance_picking` iki ara koridorlu depoda iki nokta arası mesafe (aynı koridorsa doğrudan,
  değilse alt veya üst ara koridordan dolaşma); en yakın komşu ile tur. Mesafe `int()` ile **kırpılıyor**.
- **Gruplama:** Dalga (wave) toplama ve SciPy ile konum kümeleme (k-means / Ward).
- **Alınan fikirler:** Tek toplayıcı rota problemini sipariş bazında ele alma. Sipariş gruplama ve dalga toplama
  **ilk MVP kapsamı dışında bırakıldı**; sonraki aşama için aday.

---

## Kendi mimarimize yansıması

- İş mantığı `src/warehouse_optimizer/` altında modüllere ayrıldı; arayüz (`ui/`) yalnızca gösterim yapar.
- Rota: koridor + ön/arka ara koridor grafiği (NetworkX, Dijkstra) → en yakın komşu + 2-opt. Koridor ağı
  yoksa Manhattan **yalnızca "tahmini" mod** olarak sunulur.
- Slotting: iki yöntem (sınıf tabanlı bölge cezası / hibrit puan), zorunlu fiziksel kısıt matrisi, sıralı
  uygulanabilir taşıma planı, taşıma bütçesi.
- Simülasyon: aynı siparişler, aynı model; negatif iyileşme gizlenmez; projeksiyonlar "tahmini" etiketlidir.
