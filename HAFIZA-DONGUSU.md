# Kaynaktan deneyime hafıza döngüsü

Bu akış beş parçayı mevcut araçlarla bağlar: bekleyen aday incelemesi, gerekçeli/koşullu kararlar, iş sonucundan ders, görev bağlamı ve cevap atıflarının kontrolü. Jev semantik danışmandır; puanları tek başına kayıt terfi ettirmez. Testler mekanik sözleşmeyi doğrular, gerçek Türkçe semantik kalite veya kazancı kanıtlamaz.

## Kurulum ve çalıştırma

Depodaki `araclar` dizinini mevcut kurulum yöntemiyle birlikte güncelle. Yeni modüller `hafiza_dongusu.py` ve `jev_answer.py`, yanlarındaki hafiza/bilgi_agi/jev_client modülleriyle çalışır. Python 3.10+ ve standart kütüphane yeterlidir. Linux/macOS `python3`, Windows `py -3` kullanır. Komutlarda `KASA` gerçek kasa yoludur; çalışma dizini repo köküdür.

```sh
python3 araclar/hafiza_dongusu.py --vault KASA review-pending --project-id PROJE --limit 5 --apply
python3 araclar/konsolidasyon.py --vault KASA review-pending --project-id PROJE --limit 5 --apply
python3 araclar/hafiza_dongusu.py --vault KASA context "sunum hazırlayalım" --cwd PROJE_DIZINI --budget 5000
python3 araclar/hafiza_dongusu.py --vault KASA outcome --input-json sonuc.json --apply
python3 araclar/hafiza_dongusu.py --vault KASA review-lesson --input-json inceleme.json --apply
python3 araclar/hafiza_dongusu.py --vault KASA verify-answer --project-id PROJE --input-json iddialar.json
```

İlk iki komut aynı işlemdir; ikisini arka arkaya çalıştırmak gerekmez. `--apply` yokken yazma yapılmaz (Jev'in kendi önbellek/telemetri politikası ayrı geçerlidir). Model çağrıları senkron hook'a eklenmez. Mevcut arka plan reviewer görevinin her turunda, normal oturum kaynak incelemesinden sonra bir `review-pending --limit 5 --apply` çağrısı çalıştırılır. Tek komut bir defalık bounded turdur; kendiliğinden zamanlayıcı kurmaz. Zamanlayıcısı olmayan kurulumda işletim sistemi görev zamanlayıcısından aynı komut çağrılabilir. Reviewer aynı proje kapsamını vermelidir; proje adı verilmezse yalnız kullanıcı kapsamı işlenir.

## Aday inceleme

`konsolidasyon.pending` kataloğu ve `bilgi/` altındaki proposed kartları birlikte tarar. Değişmeyen başarılı inceleme tekrarlanmaz; kaynak, aday, karşılaştırılan bilgi veya Jev ayarı değişince yeniden değerlendirilir. Hatalı/devre dışı çağrılar yeniden denenebilir. Tur başına en fazla 20, varsayılan 5 aday; aday başına mevcut Jev sınırlamaları ve en fazla 8 ilişki karşılaştırması geçerlidir. İncelenmeyen ilişki sayısı döner: eşleşme çıkmaması evrensel yenilik kanıtı değildir.

Makbuz `günlük/hafıza-makbuzları/lifecycle-review.jsonl` içindedir. Kaynak desteği/çelişki ve aynı iddia/daraltma ilişkileri danışma çıktısıdır. Katalog için mevcut deterministik assessment da makbuzdadır. Kaynak değişikliği puanları geçersiz kılar. Terfi mevcut `konsolidasyon review` / `hafiza promote` tek yazıcısıyla; bilgi kartı terfisi `bilgi_agi register` kaynak ve expected-version denetimiyle yapılır. Bu komut otomatik onay vermez.

## Gerekçe, koşul, istisna

`hafiza candidate-add` artık isteğe bağlı `--rationale` ve `--conditions` kabul eder. İkisi de kaynakta aynen bulunan en az 10 karakterlik alıntılardır; terfi sırasında korunur. Görev bağlamı ve karar geçmişi bunları kaynakla beraber bütçeye dahil eder. Mevcut supersedes/valid_from/valid_to tarihçesi değişmez.

Bilgi kartları isteğe bağlı `rationale`, `conditions`, `exceptions` alır; kaynaklardan doğrulanır ve hem yerel hem Jev seçimi sonrası bağlama taşınır. Eski kayıtlar geçerlidir; eksik gerekçe uydurulmaz. Koşulun bulunması makine tarafından her dünyasal koşulun değerlendirildiği anlamına gelmez; ajan göreve uygunluğu inceler.

## İş sonucundan ders

Önce mevcut `is_ve_ders task` ile kaynaklı işi `done` durumuna getir. Sonuç kaydı JSON örneği:

```json
{"task_id":"sunum-test","title":"Sunum yerleşim dersi","lesson":"Bu koşulda kısa cümle yöntemi doğrulandı.","conditions":"Yalnız test edilen sunum yerleşiminde.","method_path":"yontem.md","verification_path":"test-sonucu.json","verification_hash":"DOSYANIN_SHA256_DEGERI","verification_evidence":"TEST_DOSYASINDA_AYNEN_BULUNAN_EN_AZ_20_KARAKTER","verification_kind":"test_result","observed_result":"passed","actor":"worker","triggers":["sunum"]}
```

`test-sonucu.json` gerçek runner'ın ürettiği `task_id`, tamsayı `exit_code`, boolean `passed`, `command`, `finished_at` alanlarını içermelidir. `passed`/`failed` sonucu exit code ile eşleşir. Başarısız test de koşullu uyarı dersine aday olabilir; sonraki bağlamda `failed` olarak görünür, başarılı yöntem gibi sunulmaz. `user_acceptance` türünde `accepted`/`rejected` için kaynaklı kullanıcı alıntısı gereklidir. Dosya ve alan varlığı tek başına gerçek dünyada başarı kanıtı değildir: bağımsız reviewer testin kapsamını, runner çıktısını/kullanıcı beyanını ve dersin genellenebilirliğini kontrol eder. Ajanın kendi puanı kabul edilmez.

`outcome` sadece `gelen-kutusu/lesson-outcomes.jsonl` kuyruğuna yazar. Dönen receipt_id ile:

```json
{"receipt_id":"DONEN_KIMLIK","reviewed_by":"independent-reviewer","reason":"Kaynak sonuç ve dersin uygulanma koşulları karşılaştırıldı.","evidence_checked":true,"conditions_checked":true}
```

`review-lesson` kaynakları tekrar doğrular; önerenden farklı reviewer gerektirir; mevcut `is_ve_ders.put` üzerinden verified ders yazar. Tekrarlı apply yeni sürüm üretmez. Ders `ders_baglam` ve normal görev bağlamında, proje/trigger/metot/kaynak/doğrulama hash kontrollerinden sonra gelir. Sonuç kaynağı değişirse ders teslim edilmez. Kaydetmeme isteğini veya ilk beş mesaj sessizliğini aşmak için bu CLI kullanılmaz; otomatik oturum yakalama zaten mevcut capture/reviewer kapılarında kalır.

## Cevap kontrolü

Hafızaya dayalı “bunu tercih ediyorsun” gibi iddiaları cevap öncesinde şu sözleşmeyle kontrol et:

```json
[{"text":"Sunumda kısa cümle tercih ediyorsun.","citations":[{"card_id":"sunum-tercihi","path":"kaynak.md","sha256":"KAYNAGIN_SHA256_DEGERI","quote":"Kaynak kartındaki aynen doğrulanmış alıntı"}]}]
```

Katalog kaydında `card_id` yerine `memory_id` kullanılır. Geçerli güncel kayıt, kapsam, birebir alıntı ve kaynak hash'i önce deterministik kontrol edilir; ardından Jev yalnız alıntıyla iddiayı karşılaştırır. Bir çağrıda en fazla 20 iddia, her birinde 8 atıf, toplam 32000 karakter. Sonuçlar `supported`, `contradicted`, `insufficient`, `uncertain`, `degraded`; off/shadow semantik onay yerine uncertain verir. Timeout “kanıt yok” değildir, degraded'dır. Kaynak çağrı sırasında değişirse sonuç atılır. Kaynak eksik veya çelişkiliyse ajan iddiayı kaynaklı biçimde daraltır veya çıkarır; araç cevabı kendi kendine değiştirmez. Bu, yapılandırılmış atıflara dayalı araçtır; tüm serbest metindeki iddiaları kendiliğinden keşfettiği iddia edilmez.

## Kontrol ve geri dönüş

```sh
python3 -m unittest discover -s araclar -p 'test_*.py'
```

Jev `komuta/jev.json` içindeki mevcut off/shadow/on ayarıyla kontrol edilir. Off modda yerel görev bağlamı ve kaynak kapıları çalışır; otomatik terfi yoktur. Bakım zamanlayıcısını kapatmak yeni inceleme turlarını durdurur; geçmiş silinmez. Deneysel kaliteyi aynı aday havuzunda Jev açık/kapalı ve güçlü yerel baseline ile ayrıca ölç. Ücret/gecikme/yanlış kabul ve kaçırılan kaynakları ayrı raporla.

[[Ana Sayfa]]
