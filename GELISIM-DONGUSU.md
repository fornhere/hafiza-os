# Sınırlı, gölge gelişim döngüsü

`araclar/gelisim_dongusu.py`, kaynak seçiminin **puan/eşik altbileşeni** için
tekrarlanabilir bir deney yöneticisidir. Tam görev paketinin facet, alan,
karakter bütçesi ve assist birleşimini taklit etmez. Kazananı üretime uygulamaz;
kod değiştirmez, kanonik bilgi veya Mem0 yazmaz. Gerçek görevde iyileşme ancak
ayrı uçtan uca ölçümle doğrulanabilir.

## Akış

1. İncelenmiş soru etiketlerini güncel ve kaynakları doğrulanmış kartlarla dondur.
2. Ortak kaynakları, aynı kaynak içeriğini veya aynı kapsamda normalize edilmiş
   aynı soruyu paylaşan örnekleri birlikte tut; geliştirme/sınama ayrımını yap.
3. Yalnız geliştirme sorularından boşluk ve istek öneki varyasyonları üret.
4. Jev her uygun kartı bir kez puanlar. Aynı puanlarla mevcut 1.5 eşiğini ve
   1.3/1.7/1.9 adaylarını karşılaştır.
5. Eksik/gereksiz kaynak sayısı artmadan en az biri azalırsa adayı seç ve
   sınama çağrılarından **önce** bu seçimi kaydet.
6. Sınamada iki hata türünden biri artarsa reddet; artmazsa yalnız gölge aday
   raporu oluştur. İyileşme yoksa sınamayı çağırmadan dur.

Etiketler Jev puanından türetilmez. Kaynak hash'i anlamsal doğruluk kanıtı
olmadığı gibi ajan etiketi de insan kabulü değildir. Sınama sonuçlarına bakarak
başka aday seçilmez veya aynı kampanya tekrar optimize edilmez. Her iki bölümde
de pozitif ve negatif bağımsız örnekler korunur.

## Kullanım ve sürüm 2

Etiket JSON'u `label_status`, `label_review` ve `cases` içerir. İnceleme kaydı:

```json
"label_review": {
  "status": "reviewed",
  "kind": "agent",
  "reviewed_by": "reviewer-id"
}
```

`kind`: `human`, `agent` veya `fixture`. Bu alan kimlik doğrulaması değil,
inceleme beyanıdır. Gerçek inceleme yapılmadan sırf kapıyı geçmek için
doldurulmaz. `fixture` mekanik örnektir; kullanıcı faydası değildir.

Her soru: `id`, `query`, `project_id` (yoksa null), `expected_ids` (zorunlu
kartlar), `relevant_ids` (izinli kartlar), `origin`. Zorunlu küme izinli kümenin
altkümesidir; iki kümesi de boş soru desteksiz negatiftir. En az iki pozitif ve
iki negatif bağımsız aile gerekir. Aynı kaynağa dayanan sorular bağımsız değildir.

```sh
python3 araclar/gelisim_dongusu.py --vault /path/to/vault freeze \
  --labels /private/reviewed-labels.json --output /private/corpus.json
python3 araclar/gelisim_dongusu.py --vault /path/to/vault run \
  --corpus /private/corpus.json --output-dir /private/experiment-runs
```

`freeze` yalnız mevcut bilgi ağı kapılarından geçmiş, kasa içinde çözümlenen
kanıtları olan kartları alır. Dışarıda kalan karta bağlı etiket sessizce
silinmez; girdi reddedilir. Kaynak aileleri göreli yollardır ve hash haritasında
bulunmalıdır. Eski korpusun yalnız `schema` değerini artırmayın: kaynakları ve
etiketleri yeniden inceleyip `freeze` edin. Örnek `examples/improvement-demo/`
tamamen kurgu mağaza verisidir ve sürüm 2 inceleme kaydı taşır.

## Tekrar kullanım, çökme ve devam

Aynı korpus özeti tekrar çalıştırılınca ağ çağrısı yapılmaz: `status=unchanged`,
`previous_status` önceki sonucu gösterir. Başarısızlık olumsuz kalite etiketi
veya otomatik tekrar izni değildir.

İki bölümün kimlikleri ilk çağrıdan önce kalıcı deftere ayrılır. Önceki sınama
verisi yeni geliştirmeye veya sınamaya; önceki geliştirme verisi yeni sınamaya
giremez. Soru kimliği değiştirme, boşluk/büyük harf farkı veya kaynak dosyasını
yeniden adlandırma bu korumayı sıfırlamaz. Aynı içerik hash'ine sahip kaynaklar
da aynı grupta kalır. Serbest anlamsal parafraz eşitliği mekanik olarak çözülmez;
kaynak ailesi/etiket incelemesi hâlâ gereklidir.

Koruma yalnız **aynı kalıcı `output-dir`** için geçerlidir; başka dizin açmak
veya geçmişi silmek korumayı aşar. Defter kötü niyetli elle düzenlemeye karşı
imzalı bir güvenlik sınırı değildir. Otomasyon dizini sabit tutmalıdır.
Bozuk raporlar atlanmaz. Sürüm 1 raporlarının ayrılmış sınama aileleri ve mevcut
geliştirme satırları korunur; çağrı yapmış fakat geliştirme kaydı eksik kalmış
eski rapor `legacy_ledger_incomplete` ile işlemi durdurur.

Yalnız sınamaya geçmemiş timeout başarısızlığında bir kez açık
`--resume-timeout` kullanılabilir. Önceki rapor saklanır; çağrı, raporlanan token
ve **geçen yürütme süresi** birlikte hesaplanır. Denemeler arasındaki boşta süre
sayılmaz. Kod hash'leri (çalıştırıcı, Jev istemcisi, koordinasyon, kilit),
etkin/diskteki ayar, eşikler ve limitler aynı olmalıdır. Fark varsa eski rapora
dokunulmadan `resume_revision_changed` döner. Uzak model takma adının aynı
ağırlıkları sunduğu bu yerel kontrollerle ispatlanamaz.

## Bütçe, gizlilik ve otomasyon

En fazla 32 kart, 40 tohum soru, kampanya başına 60 değerlendirme çağrısı,
240 saniye ve raporlanan 200000 token. Çağrı bütçesi önceden kontrol edilir.
Son çağrı süre/token sınırını aşabilir; varsayılan istemci timeout'u korunur.
Bunlar garantili dolar sınırı değildir. `usage_unreported_calls`, eksik token
bildirimi veya başarısız çağrının bilinmeyen kullanımını gösterir; sıfır
raporlanan token ücretsiz çağrı demek değildir. Timeout devamı bütçeyi sıfırlamaz.

Kaynak, ayar ve kod sürümleri çağrı öncesi/sonrası ve son karar öncesinde yeniden
denetlenir. Tek kalıcı dosya kilidi altında eşzamanlı ikinci kampanya beklemek
yerine reddedilir. Çökme `started` bırakabilir; disk yazma hatasında kalıcı hata
raporu da garanti edilemez. Tamamlanan rapor aynı korpusla değiştirilmez.

Jev'e soru ve uygun kapsamdaki kısa kart alanları gider; etiketler, ham kaynak
dosyaları ve aile alanları değerlendirme gövdesine eklenmez. Kaynak sürümleri
istemcinin yerel istek parmak izinde kullanılır. Raporlar soru/etiket içerdiği
için özel tutulmalıdır. Keyfi sağlayıcı hata/teşhis metni rapora kopyalanmaz;
yalnız sabit hata kodları ve sınırlı metadata biçimleri kabul edilir. Bu kontrol
genel amaçlı kişisel veri temizleyicisi değildir. Negatif/boolean/geçersiz token
sayaçları ve bozuk puanlar aday üretmek yerine başarısız rapor oluşturur.

CLI çıkışları: başarı veya kalite bakımından sonuçsuz/reddedilmiş deney `0`;
`failed` veya başarısız/yarım kaydın tekrarı `1`; ön kontrol reddi `2`.
Ön kontrol, bilinen güvenli hata kodunu JSON'da verir; serbest exception metnini
vermez. Zamanlayıcı bu çıkışları başarıya çevirmemelidir.

```sh
python3 -X utf8 -m unittest discover -s araclar -p 'test_gelisim*.py' -v
python3 -X utf8 -m unittest discover -s araclar -p 'test_*privacy*.py' -v
python3 -X utf8 -m unittest discover -s araclar -p 'test_*.py'
```

Bu sürüm otomatik serbest soru üreticisi, gerçek kullanıcı sonucu etiketleyicisi,
üretime terfi veya canlı trafik deneyi kurmaz. Gölge aday raporu, gölge trafiğe
dağıtılmış sürüm değildir. Yeni incelenmiş veri olmadan sonsuz sentetik üretim ve
tekrar sınama yapılmaz. Yerel zamanlayıcı açıkça kurulursa tur başına tek korpus
işlemeli, değişmeyen durumda sessiz kalmalı ve yalnız yeni aday/hata/kaynak
yenileme ihtiyacını bildirmelidir. Bu yama zamanlayıcı veya üretim ayarı kurmaz.
