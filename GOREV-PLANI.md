# Görev çakışma planı — deneysel danışman

`python3 araclar/gorev_plani.py --input-json examples/task-plan.json`

Araç beyan edilmiş okuma/yazma alanlarından çakışmaları ve sıralı çalışma
gruplarını çıkarır. Görev çalıştırmaz, dosya kilidi almaz, izin vermez.
Örnekte katalog okuma, aktarım kodu düzeltme ve video düzenleme ilk gruptadır;
kataloğu değiştiren görev sonraki gruptadır.

Girdi tek `scope`, en fazla 32 kaynak ve 32 görev içerir. Kaynağın `id`,
`key`, `description`; görevin `id`, `description`, `reads`, `writes`,
`after`, `complete` alanları zorunludur. `after` önce tamamlanması gereken
görev kimlikleridir. Döngü ve bilinmeyen referanslar reddedilir.

Kaynak `key` mantıksal, büyük/küçük harfe duyarlı bir kimliktir; dosya yolu
çözümleyicisi değildir. `vault` yazımı `vault/catalog` ile çakışır;
`vault/a`, `vault/abc` ile çakışmaz. Aynı fiziksel kaynağa erişen alias,
symlink, farklı proje ya da uzak servis anahtarlarını çağıran taraf aynı
kimliğe eşlemelidir. Scope bir yetkilendirme kapısı değildir. Ayrı belgelerdeki
planlar birbiriyle koordine edilmez. Okuma kümeleri aynıysa birlikte planlanabilir;
bir tarafta yazma varsa çakışma vardır. `complete: false` görevler ve onların
bağımlıları dışarıda kalır. Boş ama complete bir küme, kaynak kullanmadığına
ilişkin açık çağıran beyanıdır; model bunu sağlayamaz.

`input_digest` yalnız girdinin sürümüdür; canlı dosya güncelliği kanıtı değildir.
Gerçek çalıştırıcı, kaynakları ve deklarasyonları yeniden doğrulamalı ve
kilitleri kendi edinmelidir. Gruplar girdi sırasına göre açgözlü planlanır;
en kısa toplam çalışma süresi iddiası yoktur.

## İsteğe bağlı Jev eşleştirmesi

`komuta/jev.json` içindeki diğer ayarları koruyarak `task_mapping_mode: shadow`
ekleyin. Varsayılan `off`; ana `mode: off` her şeyi kapatır. Ardından en fazla
üç görev içeren girdi için:

```sh
python3 araclar/gorev_plani.py --input-json /path/to/three-tasks.json --vault /path/to/vault --jev
```

En fazla 32 kaynak × 3 görev, tek çağrı, mevcut istemci bütçesi ve timeout'u.
Model yalnız görev ve kaynak açıklamalarını alır; dosya içeriklerini okumaz.
Girdinin açıklamalarında özel veri varsa bu dışarı gönderilir. Her kaynak için
bağımsız 0–2 puan döner; 1.5 üstü dahil öneriler gösterilir. Bu eşik pilot
tercihidir, kalibre edilmiş güven veya eksiksizlik garantisi değildir.

Öneriler `reads`, `writes`, `complete`, gruplar ve izinleri değiştirmez.
Ağ hatası ile gerçek boş eşleşmeyi `jev.degraded`, `mode` ve `diagnostics`
alanlarından ayırın. Araç arka planda otomatik çağrılmaz.

İlk sentetik pilot: 12 önceden ajan etiketli görev, 6 kaynak; tam küme
başarısı basit sözcük kesişiminde 6/12, Jev'de 11/12. Jev gerekli kaynak
kaçırmadı, bir gereksiz kaynak önerdi. Dört canlı istek 314–568 ms sürdü;
11194 girdi / 1168 çıktı tokenı. Bu küçük örnek gerçek kullanıcı faydası,
güvenli yürütme veya genel model üstünlüğü kanıtı değildir. Etiketler ve
karşılaştırıcı bağımsız kullanıcı değerlendirmesi değildir.
