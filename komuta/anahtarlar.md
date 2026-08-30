# Anahtarlar — Künye

Burada **hiçbir anahtarın değeri yazmaz.** Anayasa madde 6:
*hafıza sırrın nerede olduğunu bilebilir, ne olduğunu asla.*

Bu dosya sadece şunu söyler: hangi anahtar var, nerede duruyor, ne işe yarıyor,
ne zaman alındı. Değeri görmek istersen dosyayı sen açarsın.

**Anahtarların yeri:** `~/.config/<kullanıcı>/keys.env` — izin `600`, klasör `700`.
Bu deponun **dışında**, bilinçli olarak. Depo git ile takip ediliyor;
sır ile versiyon takibi aynı yerde yaşamaz.

## Kullanım

Ajan bir anahtara ihtiyaç duyduğunda dosyanın tamamını okumaz; sadece
ihtiyacı olanı ortama alır:

```bash
set -a; . ~/.config/<kullanıcı>/keys.env; set +a
```

## Künye

| Anahtar | Ne işe yarar | Alındı | Not |
|---|---|---|---|
| <!-- ÖRNEK_API_KEY --> | | | |
