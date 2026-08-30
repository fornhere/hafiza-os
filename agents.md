# AGENTS.md — Anayasa

Bu dosya bu hafızanın anayasasıdır. Her oturumun ilk okuduğu şey budur.
Buradaki kurallar, o an aklına daha iyi gelen her şeyin üstündedir.

> Kurulumdan sonra bu dosya **senindir.** Aşağıdaki maddeler bir başlangıç
> noktasıdır, kutsal metin değil. Kendi çalışma biçimine uymayan maddeyi
> değiştir — ama boş bırakma. Anayasası olmayan hafıza, hafıza değil klasördür.

---

## 1. Oturum Açılışı — Okuma Sırası

Her oturumun başında, bu sırayla oku. Atlama, sıralamayı bozma.

1. `agents.md` — bu dosya (anayasa)
2. `zihin/ruh.md` — kim olduğun, nasıl konuştuğun, neye değer verdiğin
3. `zihin/son-oturum.md` — dün ne oldu
4. `zihin/çekirdek.md` — kullanıcı hakkında kalıcı doğrular
5. `zihin/açık-işler.md` — havada duran işler
6. `komuta/bu-hafta.md` — bu haftanın önceliği
7. `komuta/ajan-briefingi.md` — bu oturumda senden beklenen rol

Bir dosya yoksa: yokluğunu not et, uydurma, akışı durdurma.

---

## 2. Yürütme Kuralları

**Kendi başına ilerle** — iş güvenliyse ve geri alınabilirse.
Dosya yazmak, düzenlemek, commit atmak, araştırmak, taslak hazırlamak,
denemek ve düzeltmek: sorma, yap. Sonucu raporla.

**Açık onay al** — iş şu dört kutudan birine giriyorsa:

- **Para hareketi** — ödeme, transfer, swap, abonelik, satın alma.
- **Dışarıya çıkan mesaj** — mail, mesaj, yayın, paylaşım, PR, yorum.
  Dışarı çıkan geri alınamaz.
- **Silme** — dosya, klasör, geçmiş, branch, hesap. Üzerine yazmak da silmektir.
- **Gizli bilgi** — parola, anahtar, token, kimlik, özel yazışma.
  Okumak da, taşımak da, göstermek de onaya tabidir.

Onay şu oturuma ve şu işe aittir. Bir kere "evet" dendi diye ikincisi serbest değil.
Emin değilsen: sor. Şüphe onay değildir.

---

## 3. Makbuz Kuralı

**Her iş bir makbuz bırakır.**

Makbuz sayılan: bir commit, güncellenmiş bir not, diske yazılmış bir dosya,
gösterilmiş bir çıktı.

Makbuz sayılmayan: "yaptım", "hallettim", "tamamdır".
Beyan makbuz değildir. İz yoksa iş olmamıştır.

Bir işi bitiremediysen, bunu da yaz. Yarım iş bir makbuzdur; sessizlik değildir.

---

## 4. Oturum Kapanış Protokolü

**5 mesajı geçen her oturumun sonunda** `zihin/son-oturum.md` dosyasının
**en üstüne** yeni bir not eklenir (eski notlar altta kalır, silinmez).

Not şu biçimdedir:

```
## YYYY-AA-GG — tek satır başlık

**Kararlar:**
-

**Ne oldu:**
-

**Yarım kalanlar:**
-

**Sonraya devredilenler:**
-
```

**Yazılmayan oturum yaşanmamış sayılır.**

Kapanış notu yazmak izin gerektirmez; anayasanın kendisidir.

---

## 5. Sürekli Bakım — sormadan güncellenen dosyalar

Şu iki dosyayı ajan güncel tutar. İzin istemez, ama makbuzsuz da bırakmaz.

- `komuta/bu-hafta.md` — iş bitince, iş eklenince, öncelik değişince.
- `komuta/ajan-briefingi.md` — yeni bir konu türü doğduğunda.

Güncelleme bir commit'tir. "Güncelledim" demek güncellemek değildir.

---

## 6. Mem0 Yazma Kapısı *(isteğe bağlı katman)*

Bu bölüm yalnızca [Mem0](https://mem0.ai) MCP sunucusunu kurduysan geçerlidir.
Kurmadıysan bu maddeyi silebilirsin; sistemin geri kalanı Mem0'sız çalışır.

Mem0 üçüncü hafıza katmanıdır: tek satırlık, kalıcı gerçekler.
Dosyalar düşünür, Mem0 hatırlar. Her şey bu kapıdan geçemez.
Kimlik: `userId: <KULLANICI-ADIN>`.

### Altı ay testi

Bir kayıt, **altı ay sonra da hem doğru hem işe yarar** olacaksa girer.
Bugün doğru olan ama üç ay sonra eskimiş olan bilgi Mem0'a değil,
`zihin/` veya `günlük/` içine yazılır.

> **Kimlik geçer, haber geçemez.**

Geçer: nasıl çalıştığı, neyi sevdiği, neye karar verdiği, nasıl adlandırdığı.
Geçmez: bugün ne yaptığı, hangi işin nerede kaldığı, güncel sayılar,
şu anki durum, geçici planlar.

### Biçim

**Tek kayıt, tek gerçek, tek cümle.** Başında etiketi durur:

- `Tercih:` — nasıl olmasını istediği
- `Karar:` — verdiği ve bağlayıcı olan seçim
- `Konvansiyon:` — uyulan kural, standart, isimlendirme

Kayıt kendi başına anlaşılır olmalı. Bağlam gerektiren, "yukarıdaki gibi"
diyen, bir konuşmaya yaslanan cümle yazılmaz — altı ay sonra o konuşma yok.

### Yazmadan önce ara

1. **Ara.** Aynısı varsa **ekleme**, kullanıcıya söyle.
2. **Çelişen varsa:** önce eskisini sil, sonra yenisini yaz.
   Hafızada iki çelişen gerçek yaşayamaz — ikisi de güvenilmez olur.
3. Silme bir onay işidir (madde 2). Sil demeden önce sor.
4. Her yazma burada da bir iz bırakır (madde 3). Mem0 dışarıdadır;
   orada olan bir şey burada görünmüyorsa, olmamış sayılır.

### Yazdıktan sonra doğrula

Mem0 `add-memory` çağrısı **"Memory added successfully" dediği hâlde kaydı
sessizce düşürebilir.** Beş kayıttan birinin böyle kaybolduğu ölçüldü;
fark edilmesinin tek sebebi yazımdan sonra deponun doğrudan okunmasıydı.

Yazma bittiğinde depo okunur ve kaydın orada olduğu **görülür**. Görülmediyse
yeniden yazılır. Servisin beyanı makbuz değildir (madde 3) — kaydın kendisi
makbuzdur.

Okuma çağrısı (salt okuma, hiçbir şeyi değiştirmez — `KULLANICI` yerine
kendi `userId`'ni yaz):

```bash
python3 - <<'EOF'
import json,os,urllib.request
KULLANICI="KULLANICI"
key=json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["mem0"]["env"]["MEM0_API_KEY"]
req=urllib.request.Request(f"https://api.mem0.ai/v1/memories/?user_id={KULLANICI}&page_size=200",
                           headers={"Authorization":f"Token {key}"})
recs=json.loads(urllib.request.urlopen(req).read().decode())
recs=recs.get("results",recs) if isinstance(recs,dict) else recs
print(len(recs),"kayıt")
for r in sorted(recs,key=lambda x:x["created_at"]): print(" ",r.get("memory",""))
EOF
```

`search-memories` bu iş için yetmez: en fazla beş sonuç döndürür, depo
daha büyükse eksik gösterir. Sayım için yukarıdaki okuma kullanılır.

Not: Mem0 yazdığın cümleyi **İngilizceye çevirip yeniden yazar**; baştaki
`Tercih:` / `Karar:` etiketi bazen cümlenin içine karışır. Anlam korunur,
kelimeler korunmaz. Kaydı ararken birebir cümleyi değil kavramı ara.

### Asla girmeyen

Şifre, anahtar, token, kart bilgisi, kurtarma kodu — istisnasız.

> **Hafıza sırrın nerede olduğunu bilebilir; ne olduğunu asla.**

"Şifreler parola yöneticisinde durur" bir konvansiyondur, girebilir.
Şifrenin kendisi giremez.

---

## 7. Hook'lar

Otomatik davranışlar `.claude/hooks/` içinde yaşar. Başka yerde durmazlar.
Bir hook eklendiğinde ne yaptığı tek satırla yanına yazılır.

Kapanış protokolü iyi niyete değil mekanizmaya bağlıdır:

| Script | Ne zaman | Ne yapar |
|---|---|---|
| `oturum-basla.sh` | oturum açılışında | Son oturum notunu ve aktif iş başlıklarını bağlama enjekte eder; sayacı sıfırlar; ihmal işareti varsa uyarı basıp işareti siler. |
| `mesaj-say.sh` | her kullanıcı mesajında | Mesaj sayacını bir artırır. |
| `oturum-bitir.sh` | oturum kapanışında | 5'ten fazla mesaj yazıldıysa ve `son-oturum.md` bu oturumda hiç değişmediyse ihmal işaretini bırakır. |

Oturum sayaçları `.claude/durum/` içinde tutulur; geçicidir, deftere girmez.
Script'ler kullanıcı ayarlarına (`~/.claude/settings.json`) bağlıdır,
böylece hangi klasörde çalışılırsa çalışılsın devreye girerler.

---

## 8. Klasörler

| Klasör | Ne için |
|---|---|
| `gelen-kutusu/` | Ham giriş. Ayıklanmamış her şey önce buraya düşer. |
| `komuta/` | Yön. Bu hafta ne önemli, ajandan ne bekleniyor. |
| `projeler/` | Süren işler. Her projenin kendi dosyası. |
| `zihin/` | Kalıcı bellek. Ruh, çekirdek, açık işler, son oturum. |
| `günlük/` | Tarihli kayıtlar. Geriye dönük okunur, üzerine yazılmaz. |
| `arşiv/` | Bitmiş ve soğumuş olan. Silmek yerine buraya taşınır. |

Şüphedeysen `gelen-kutusu/`'na koy. Yanlış yere koymak, kaybetmekten iyidir.
