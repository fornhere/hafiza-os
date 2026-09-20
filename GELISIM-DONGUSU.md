# Sınırlı, gölge gelişim döngüsü

`araclar/gelisim_dongusu.py` kaynak seçiminin **puan/eşik altbileşeni** için
tekrarlanabilir bir deney yöneticisidir. Tam görev paketinin facet, alan,
karakter bütçesi ve assist birleşimini taklit etmez. Kazananı üretime uygulamaz;
kod değiştirmez, kanonik bilgi veya Mem0 yazmaz. Gerçek görevde iyileşme ancak
ayrı uçtan uca ölçümle doğrulanabilir.

## Akış

1. İncelenmiş soru etiketlerini güncel, kaynakları doğrulanmış bilgi kartlarıyla dondur.
2. Ortak kaynakları bulunan örnekleri aynı grupta tut; grupları geliştirme/sınama diye ayır.
3. Geliştirme sorularından boşluk ve istek öneki varyasyonları üret. Bunlar sınırlı yüzey testleridir; zengin serbest parafraz üretimi değildir.
4. Jev her uygun kaynağın soruyu destekleme puanını bir kez üretir. Aynı puanlardan mevcut 1.5 eşiği ve 1.3/1.7/1.9 adayları kodla karşılaştırılır.
5. Eksik ve gereksiz kaynak sayısı artmadan en az birinde azalma varsa aday seçilir. Sonra daha önce görülmeyen kaynak ailelerinden sınama sorularına bakılır.
6. Sınamada iki hata türünden biri artarsa reddet; artmazsa yalnız gölge aday raporu oluştur. İyileşme yoksa dur.

Etiketler Jev puanından türetilmez. Kaynak doğruluğu mekanik, ilgililik
etiketleri ayrıca insan/ajan tarafından incelenmiş olmalıdır. Ajan etiketi
insan kabulü değildir. Kod başlangıç doğrulaması yapı/yol/hash/kapsamı denetler;
etiketin anlamsal doğruluğunu ispatlayamaz. Üretici veya aday seçiciye etiketli
sınama sonuçlarıyla tekrar optimizasyon yaptırılmamalıdır.

## Kullanım

Etiket JSON'u `label_status` ve `cases` içerir. Her soru için `id`, `query`,
`project_id` (yoksa null), `expected_ids` (zorunlu), `relevant_ids` (izinli),
`origin` gerekir. Zorunlu kimlikler izinli kümenin altkümesidir. Boş kümeler
cevabı olmayan negatif sorudur. En az iki pozitif ve iki negatif bağımsız
kaynak ailesi bulunmalıdır. Kaynak ailesi bölünmesi, varyasyon üretiminden önce yapılır.

```sh
python3 araclar/gelisim_dongusu.py --vault /path/to/vault freeze \
  --labels /private/reviewed-labels.json --output /private/corpus.json
python3 araclar/gelisim_dongusu.py --vault /path/to/vault run \
  --corpus /private/corpus.json --output-dir /private/experiment-runs
```

Freeze yalnız kasa içinde çözümlenen kaynakları olan, mevcut bilgi ağı kapılarından
geçmiş kartları alır; dış varlıklar dışarıda kalır. Dışarıda kalan karta bağlı
etiket varsa sessizce değiştirilmez, girdi reddedilir. Kaynaklar model çağrısı
öncesinde ve sonrasında denetlenir. Başka proje kartları çağrıya gönderilmez.
Soru ve kısa kart ifadeleri mevcut Jev hizmetine gönderilir; ham kaynak dosyaları
gönderilmez. Deney çıktıları özel tutulmalıdır.

Aynı korpus özeti ikinci kez çalıştırıldığında ağ çağrısı yapılmaz. Sonuç
`unchanged`, önceki durum `previous_status` olur. Kaynaklar değişince yeni
incelenmiş korpus gerekir. Daha önce ayrılmış sınama ailesi yeni dosya veya
ayar değişikliğiyle yeniden kullanılamaz. Bu koruma yalnız aynı kalıcı
`output-dir` defteri için geçerlidir; yeni dizin açmak veya kayıt silmek
korumayı aşar. Otomasyon dizini sabit tutmalıdır.

Timeout sonrası, yalnız sınama aşamasına geçilmemiş başarısız deneyde,
bir kez açık `--resume-timeout` kullanılabilir. Önceki rapor saklanır,
çağrı/token bütçeleri birlikte hesaplanır. Otomasyon bu bayrağı kullanmaz.
Crash/bozuk yanıt diğer başarısızlıklar otomatik tekrarlanmaz.

## Bütçe ve kontrol

- En fazla 32 kaynak, 40 tohum soru, 60 toplam değerlendirme çağrısı; tahmini çağrı sayısı başlamadan denetlenir.
- Deneme başına 240 saniye; toplam raporlanan 200000 token. Son çağrı sınırı aşabilir ve sağlayıcının raporlamadığı/timeout olmuş kullanım bilinmeyebilir. Bunlar garantili dolar sınırı değildir.
- Varsayılan istemci timeout'u aynen kullanılır. Deney için uzun timeout gerekiyorsa ayrı deney kasası kullanın; üretim ayarını değiştirmeyin.
- Tek kalıcı dosya kilidi; eşzamanlı ikinci deney beklemek yerine hata verir.
- Kaynak/ayar değişimi, bozuk veya eksik model cevabı sonuç üretimini durdurur. Hata, olumsuz kalite etiketi sayılmaz.
- Tekrarlanabilir başarılı/başarısız ve sınamada reddedilen yollar birim testleriyle doğrulanır.

Örnek `examples/improvement-demo/` tamamen kurgu mağaza verisidir; kişisel
hafıza içermez. Jev kapalıysa canlı run `failed` olur, kalite sonucu uydurmaz.
Örnek klasörün özel bir kopyasına Jev yapılandırması ekleyerek sınanabilir.

## Otonomi sınırı

Çalıştırıcı yeni **incelenmiş** korpus geldiğinde varyasyon, ölçüm, aday seçimi
ve raporlamayı kendi yapar. Genel dağıtım zamanlayıcı kurmaz. Yerel zamanlayıcı
aynı kalıcı defterle tur başına tek korpus işlemelidir; değişmeyen durumda sessiz
kalmalı, yeni aday/hata/kaynak yenileme ihtiyacında bildirmelidir.

İlk sürümün otomatik serbest soru üreticisi, gerçek kullanıcı sonucu etiketleyicisi,
üretime terfi mekanizması veya canlı trafik deneyi yoktur. Gölge aday raporu,
gölge trafiğe dağıtılmış sürüm anlamına gelmez. Yeni etiketli veri gelmeden
sonsuz sentetik üretim ve tekrar sınama yapılmaz.
