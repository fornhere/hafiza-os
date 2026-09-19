# Eski kayıt uzlaştırma

`araclar/kayit_uzlastir.py` yalnız `active` durumundaki, kaynak hash'i olmayan ve
`source_revision_unreviewed` nedeniyle erişime kapalı eski katalog kayıtlarını
kabul eder. Yeni tercih terfi aracı değildir. Ana görev ajanı yazmaz; ayrı
`codex-consolidator` inceleme rolü kaynak anlamını ve kapsamını doğrular.

`narrow`, kaynakta desteklenmeyen ekleri çıkarır. Daha kısa cümle şartı tek
başına anlamsal daralma ispatı değildir; bu karar inceleyene aittir. Tarihsel
kaynak özeti, özgün kullanıcı beyanı doğrulaması veya yeni kullanıcı kabulü
sayılmaz. Güven alanı `legacy-source-summary-reviewed` olur. Kimlik, konu,
kapsam, tür, gözlem ve geçerlilik tarihleri korunur. Yeni kaynak anchor'ı ve
kanıt kaynakta aynen bulunmalıdır. `quarantine` cümleyi veya geçmişi silmez;
yalnız kaydı etkin erişimden çıkarır.

Girdi örneği (hash'leri inceleme anında gerçek dosyalardan hesaplayın):

```json
{
  "memory_id": "user-pref-file-names",
  "action": "narrow",
  "expected_catalog_hash": "sha256:<catalog-text-sha256>",
  "expected_source_hash": "sha256:<source-text-sha256>",
  "expected_statement": "Kullanıcı açıklayıcı adları tercih eder ve numaralı adları kullanmaz.",
  "statement": "Kullanıcı açıklayıcı adları tercih eder.",
  "source_anchor": "# Dosya adı tercihleri",
  "evidence": "Açıklayıcı dosya adı tercihi kaydedildi.",
  "reviewed_by": "codex-consolidator",
  "semantic_reviewed": true,
  "reason": "Kaynak yalnız açıklayıcı ad tercihini destekliyor; numara yasağı desteklenmiyor."
}
```

```sh
python3 araclar/kayit_uzlastir.py --vault KASA --input-json inceleme.json
python3 araclar/kayit_uzlastir.py --vault KASA --input-json inceleme.json --apply
python3 araclar/hafiza.py --vault KASA validate
python3 araclar/hafiza.py --vault KASA sync
python3 araclar/hafiza.py --vault KASA sync --apply
python3 araclar/hafiza.py --vault KASA audit
```

Karantina girdisinde `action=quarantine` kullanın, `statement` alanını çıkarın.
Her girdi yalnız bir kayıt içindir. Dry-run sonucunu inceleyip aynı girdiyi
apply edin; arada katalog/kaynak sürümü değişirse yeniden inceleme gerekir.
Aynı uygulanmış girdi tekrar gönderildiğinde eski katalog hash'i reddedilir.

Yerel yazıcı kilidi diğer katalog yazıcılarıyla ortaktır. Eski/yeni kayıt ve
kaynak sürümü `günlük/kayit-uzlastirma.jsonl` eklemeli denetim dosyasına
`prepared` olarak yazılır; katalog atomik yazılıp geri okunduktan sonra
`applied` ve son katalog hash'i eklenir. Yalnız prepared kalan işlem kesintili
sayılır; başarı değildir. Katalog ve denetim geçmişini karşılaştırmadan
körü körüne yeniden uygulamayın. Bu dosya yerel hafıza Git izin listesinde
bulunur; otomatik push yapılmaz.

Yerel uygulama Mem0'ı güncellemez. Sonuçtaki `mem0_sync_required` ayrı
sync/audit gerektiğini belirtir. Sync dry-run farklarında sıfır dışı çıkış
kodu beklenebilir; apply sonrasında gerçek verified sayısını ve audit drift,
kayıp, yetim ve tekrar alanlarını kontrol edin. Erişime uygun kayıt sayısı
sorgu sıralama başarısı veya kullanıcı zaman tasarrufu değildir.
