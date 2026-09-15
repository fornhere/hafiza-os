# Bağlamın araçta kullanıldığını doğrulama

`kullanim_kontrol.py` salt okunur bir kontrol aracıdır. Hafıza kaydı veya kalıcı
telemetri üretmez; ilk beş mesajda da çalışma dosyaları üzerinden geçici
doğrulama yapılabilir. Anlamlı sonuçların kalıcı kaydı yalnız mevcut mesaj
eşiği ve kaydetmeme kapısından geçen makbuz akışına bırakılır.

`python3 araclar/kullanim_kontrol.py --package paket.json --invocation cagri.json`

Paket `gorev_baglam.build_task_package` çıktısıdır. Çağrı dosyası `tool`,
`call_id`, `actual_paths` ve isteğe bağlı `required_role` içerir. Varsayılan
rol `identity` olur. Onaylı kaynak dosyanın kökü, onay kanıtı ve hash'i
doğrulanır; dosya actual_paths içinde yoksa kontrol başarısızdır.

Yalnız hazırlanmış çağrı argümanı `preflight_only` sonucu verir; araç çalıştı
iddiası değildir. Gözlenen araç kaydını doğrulamak için `trace` alanında
`path`, dosyanın `sha256` değeri ve kayıtta aynen bulunan JSON `evidence`
verilir. Bu JSON aynı `tool`, `call_id` ve `actual_paths` alanlarını taşımalıdır.
Başarılı eşleşme `trace_matched` olur. Bu yerel kaynak bütünlüğü kontrolüdür;
çağrı kaynağının bağımsız kriptografik doğrulaması değildir. Gerçek araç
çıktısından çıkarılmalı, çalışmamış çağrı için üretilmemelidir.

İsteğe bağlı `--outcome sonuc.json`, `technical` için unknown/passed/failed,
`user` için unknown/accepted/rejected kabul eder. Çıktıda bunlar açıkça
declaration olarak gösterilir: dosyanın varlığı, araca eklenmesi veya teknik
kontrol kullanıcının kabulünü otomatik üretmez. Kullanıcı kabulü yalnız
gerçek kullanıcı geri bildiriminden kaydedilir. Başarılı görsel estetiği
bu CLI tek başına belirleyemez.

## Gerçek rollout üzerinden kontrol

### Exec içinden üretim kapısı

Önce paket ve üretim argümanlarını geçici çalışma dosyalarına hazırla. Argüman
JSON'unda prompt ve referenced_image_paths bulunur. Şu akış doğrulayıcı sıfır
çıkış kodu vermeden üretim aracını çağırmaz; dönen argümanlar değiştirilmez:

```javascript
const validation = await tools.exec_command({cmd: 'python3 araclar/kullanim_kontrol.py --package /tmp/paket.json --image-arguments /tmp/image-args.json', workdir: '/PATH/TO/VAULT'});
if (validation.exit_code !== 0) throw new Error('Referans doğrulaması tamamlanmadı');
const args = JSON.parse(validation.output);
const result = await tools.image_gen__imagegen(args);
generatedImage(result);
```

Yollar örnektir; mevcut kasa ve geçici dosyaların gerçek yolları kullanılır.
`prepare_image(package,args)` doğrulanan aynı nesneyi döndürür. Recent-images
mekanizmasıyla belirsiz referans, eksik prompt veya eksik/yanlış kimlik
dosyası hata verir. Bu yürütülebilir iş akışı kapısıdır; başka yoldan araç
çağrılmasını önleyen küresel hook değildir. Üretimin başarısını veya estetik
kabulü kanıtlamaz, kalıcı hafıza yazmaz.

`python3 araclar/kullanim_kontrol.py --package paket.json --transcript rollout.jsonl --session-id ANA_OTURUM --call-id CAGRI`

Bu mod kullanıcı metnini çıktıya kopyalamaz. İlk session_meta sahipliğini ve
tekil çağrı kimliğini doğrular; `response_item` içindeki function_call veya
custom_tool_call ile eşleşen çıktı kaydını okur. Yalnız doğrudan image_gen
JSON çağrısının `referenced_image_paths` alanı dosya kullanım kanıtıdır.
Prompt içinde geçen yol, başka çağrı, JavaScript exec sarmalayıcısı veya
`num_last_images_to_include` bilinmiyor sonucunda kalır; sarmalayıcı kodu
çalıştırılmaz veya regex ile çalışmış sayılmaz. Bu yüzden bazı gerçek
çalıştırmalar doğrulanamayabilir; bilinmiyor başarı anlamına gelmez.

Sonuç `recorded_tool_arguments` olsa da yalnız kaydedilmiş araç girdisini
gösterir. Çıktının bulunması `present_unclassified`, açık isError true ise
`reported_error` olur. Teknik başarı ve kullanıcı kabulü bağımsız olarak
unknown kalır. Bozuk kayıt veya kopya çağrı kimliği doğrulamayı reddeder.


## Somut kaynak sürümünü değiştirme

Varlık manifestindeki isteğe bağlı `replaces_memory_ids` yalnız incelenmiş,
tam kayıt kimliklerini içerir. Bu alan, eski somut dosya sürümü iddiasını
güncel görev bağlamından ve uzak arama sonucunun yerel karşılığından çıkarır;
katalog veya uzak kayıt silmez. Yeni varlığın onay/hash/yol kontrolü geçmezse
eskiye dönülmez, asset_revision_conflict gösterilir. Genel kişilik/üslup
tercihlerini veya aynı konudaki bütün kayıtları bu alana koyma. Tarihsel
kaynağın kalıcı katalogdaki durumu ayrı inceleme aşamasının sorumluluğudur.
