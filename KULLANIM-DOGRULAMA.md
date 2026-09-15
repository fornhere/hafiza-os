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
