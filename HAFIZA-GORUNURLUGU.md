# Hafıza görünürlüğü

Üç farklı durum: bağlama getirildi, ajan kullandığını açıkladı, dosyaya yazıldığı doğrulandı. İlki ikincisini kanıtlamaz.

`python3 araclar/hafiza_gorunurluk.py --help` kaynak ve yazım bildirimlerinin doğrulayıcısıdır. Kullanım girdisi görev paketi, kaynak ve somut etki açıklamasıdır. Kaynak sürümü doğrulanır; etki açıklaması agent_reported kalır. Bu araç ajanın düşüncesini veya gerçek yararı ölçmez.

`bilgi_agi.py register --apply` anlamlı yazımdan sonra dosyayı geri okuyup notice döndürür. Notice, kullanıcıya zaten gösterildiği anlamına gelmez; ajan kısa metni gerçek sonucuyla birlikte iletir. Dry-run ve aynı içerik tekrarında bildirim yoktur.

Hook ilgili görev bağlamının yanında görünür kullanım yönergesini verir. Rutin kapanış zorlaması yoktur. Aynı bilgi etkisizse veya değişmemişse bildirim tekrarlanmaz; bu tekrar kontrolü ajan yönergesidir, teslimat onayını izleyen bir UI servisi değildir.
