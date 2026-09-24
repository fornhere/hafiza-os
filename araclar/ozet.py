#!/usr/bin/env python3
"""Dizin özeti sidecar üretir: her dizine deterministik `.ozet.md` (L0/L1)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

KAPSAM = ("projeler", "zihin", "komuta")
HARIC = {"günlük", "gelen-kutusu", "arşiv", "araclar", ".obsidian"}
KAPAK_ADLARI = ("OKU.md", "DURUM.md", "README.md")
OZET_ADI = ".ozet.md"
L0_SINIR = 256
DOSYA_OZET_SINIR = 200
GOVDE_SINIR = 4000
DOSYA_SINIRI = 32
BASLIK_SINIRI = 3
HARITA_HEDEFI = 2500
# hafiza.py içindeki desenlerin kopyası; import döngüsü kurmamak için burada durur.
SIR_DESENLERI = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:api[_ -]?key|token|parola|şifre)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def sir_var(satir: str) -> bool:
    """Satır sır deseni içeriyor mu."""
    return any(desen.search(satir) for desen in SIR_DESENLERI)


def haric_mi(ad: str) -> bool:
    """Dizin adı kapsam dışında mı (nokta ile başlayanlar dahil)."""
    return ad.startswith(".") or ad in HARIC


def hash_metin(metin: str) -> str:
    """Metnin sözleşmedeki sha256 gösterimi."""
    return "sha256:" + hashlib.sha256(metin.encode("utf-8")).hexdigest()


def kirp(metin: str, sinir: int) -> str:
    """Boşlukları tekleştirip sınırı aşan metni kelime sınırında kırpar."""
    metin = re.sub(r"\s+", " ", metin).strip()
    if len(metin) <= sinir:
        return metin
    kesit = metin[: sinir - 1].rstrip()
    bosluk = kesit.rfind(" ")
    if bosluk > sinir // 2:
        kesit = kesit[:bosluk]
    return kesit.rstrip(" ,;:-·") + "…"


def temiz_satirlar(metin: str) -> list[str]:
    """Frontmatter, kod bloğu ve sır satırları çıkarılmış gövde satırları."""
    satirlar = metin.splitlines()
    basla = 0
    if satirlar and satirlar[0].strip() == "---":
        basla = len(satirlar)
        for sira in range(1, len(satirlar)):
            if satirlar[sira].strip() in ("---", "..."):
                basla = sira + 1
                break
    temiz: list[str] = []
    kod = False
    for satir in satirlar[basla:]:
        cip = satir.lstrip()
        if cip.startswith("```") or cip.startswith("~~~"):
            kod = not kod
            continue
        if kod or sir_var(satir):
            continue
        temiz.append(re.sub(r"<!--.*?-->", "", satir))
    return temiz


def ilk_paragraf(satirlar: list[str]) -> str:
    """H1 ve tablo/alıntı satırlarını atlayıp ilk anlamlı paragrafı verir."""
    paragraf: list[str] = []
    for satir in satirlar:
        golge = satir.strip()
        if not golge:
            if paragraf:
                break
            continue
        if golge.startswith("#") or golge.startswith("|") or golge.startswith(">") or set(golge) <= set("-=*_"):
            if paragraf:
                break
            continue
        if not re.sub(r"\[\[[^\]]*\]\]|[·•*_\-\s]", "", golge):
            if paragraf:
                break
            continue
        paragraf.append(golge)
    return re.sub(r"\s+", " ", " ".join(paragraf)).strip()


def ilk_cumle(metin: str) -> str:
    """Metnin ilk cümlesi; nokta yoksa metnin kendisi."""
    eslesme = re.search(r"(?<=[.!?])\s", metin)
    return metin[: eslesme.start() + 1] if eslesme else metin


def basliklar(satirlar: list[str]) -> list[str]:
    """Gövdedeki H2 ve altı başlıkların metinleri."""
    bulunan = []
    for satir in satirlar:
        eslesme = re.match(r"\s{0,3}(#{2,6})\s+(.+?)\s*#*\s*$", satir)
        if eslesme:
            bulunan.append(re.sub(r"[`*_\[\]]", "", eslesme.group(2)).strip())
    return bulunan


def dosya_ozeti(yol: Path) -> tuple[str, list[str]]:
    """Bir .md dosyasının kısa özeti ve başlık listesi."""
    try:
        metin = yol.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "", []
    satirlar = temiz_satirlar(metin)
    return kirp(ilk_paragraf(satirlar), DOSYA_OZET_SINIR), basliklar(satirlar)


def dosya_satiri(ad: str, ozet: str, bas: list[str]) -> str:
    """Dosya listesi satırını sözleşmedeki biçimde kurar."""
    parca = f"- `{ad}` — {ozet or '(özet yok)'}"
    if bas:
        parca += " [başlıklar: " + "; ".join(bas[:BASLIK_SINIRI]) + "]"
    return parca


def l0_uret(dizin: Path, dosya_ozetleri: dict[str, str], alt_l0: dict[str, str]) -> str:
    """Kapak dosyasından, yoksa dosya/alt dizin özetlerinden L0 türetir."""
    for kapak in KAPAK_ADLARI:
        if kapak in dosya_ozetleri and dosya_ozetleri[kapak]:
            return kirp(dosya_ozetleri[kapak], L0_SINIR)
    cumleler = [ilk_cumle(ozet) for ozet in dosya_ozetleri.values() if ozet]
    if not cumleler:
        cumleler = [ilk_cumle(ozet) for ozet in alt_l0.values() if ozet]
    if not cumleler:
        return f"{dizin.name} dizini."
    return kirp(" ".join(cumleler), L0_SINIR)


def govde_kur(ad: str, l0: str, dosyalar: list[str], altlar: list[str]) -> str:
    """L1 gövdesini kurar; 4000 karakteri aşarsa dosya listesini kısaltır."""
    toplam = len(dosyalar)
    sayi = min(DOSYA_SINIRI, toplam)
    while True:
        parcalar = [f"# {ad}", "", l0, ""]
        if dosyalar:
            parcalar.append("## Dosyalar")
            parcalar.extend(dosyalar[:sayi])
            kalan = toplam - sayi
            if kalan:
                parcalar.append(f"- ... ve {kalan} dosya daha")
            parcalar.append("")
        if altlar:
            parcalar.append("## Alt klasörler")
            parcalar.extend(altlar)
            parcalar.append("")
        govde = "\n".join(parcalar).rstrip() + "\n"
        if len(govde) <= GOVDE_SINIR or sayi == 0:
            return govde
        sayi -= 1


def frontmatter(dizin_yolu: str, tarih: str, sources: dict, subdirs: dict) -> str:
    """Sözleşmedeki frontmatter bloğu."""
    return (
        "---\n"
        "kind: ozet\n"
        f"dir: {dizin_yolu}\n"
        f"generated_at: {tarih}\n"
        f"sources: {json.dumps(sources, ensure_ascii=False, sort_keys=True)}\n"
        f"subdirs: {json.dumps(subdirs, ensure_ascii=False, sort_keys=True)}\n"
        "---\n"
    )


def frontmatter_oku(metin: str) -> dict | None:
    """Var olan özetin sources/subdirs hash'lerini okur."""
    satirlar = metin.splitlines()
    if not satirlar or satirlar[0].strip() != "---":
        return None
    alanlar = {}
    for satir in satirlar[1:]:
        if satir.strip() == "---":
            break
        anahtar, _, deger = satir.partition(":")
        alanlar[anahtar.strip()] = deger.strip()
    try:
        return {
            "sources": json.loads(alanlar.get("sources", "{}")),
            "subdirs": json.loads(alanlar.get("subdirs", "{}")),
        }
    except json.JSONDecodeError:
        return None


def l0_ayikla(metin: str) -> str:
    """Var olan bir özet dosyasından L0 satırını çıkarır."""
    for satir in temiz_satirlar(metin):
        golge = satir.strip()
        if golge and not golge.startswith("#"):
            return golge
    return ""


def atomik_yaz(yol: Path, icerik: str) -> None:
    """Geçici dosya + rename ile atomik yazar."""
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(icerik, encoding="utf-8")
    os.replace(gecici, yol)


def dizinler(vault: Path) -> list[Path]:
    """Kapsamdaki dizinleri yapraktan köke doğru sıralar."""
    sonuc: list[Path] = []

    def gez(dizin: Path) -> None:
        for cocuk in sorted(dizin.iterdir()):
            if cocuk.is_dir() and not haric_mi(cocuk.name):
                gez(cocuk)
        sonuc.append(dizin)

    for ad in KAPSAM:
        kok = vault / ad
        if kok.is_dir():
            gez(kok)
    return sonuc


def plan(vault: Path, tarih: str) -> list[dict]:
    """Her dizin için hedef özet içeriğini ve durumunu hesaplar (yazmaz)."""
    vault = vault.resolve()
    bugun = tarih
    icerikler: dict[Path, str] = {}
    l0_tablosu: dict[Path, str] = {}
    plani: list[dict] = []
    for dizin in dizinler(vault):
        md = sorted(
            (yol for yol in dizin.iterdir() if yol.is_file() and yol.suffix == ".md" and not yol.name.startswith(".")),
            key=lambda yol: yol.name,
        )
        alt_dizinler = [
            cocuk for cocuk in sorted(dizin.iterdir())
            if cocuk.is_dir() and not haric_mi(cocuk.name) and cocuk in icerikler
        ]
        if not md and not alt_dizinler:
            continue
        sources, ozetler, dosya_satirlari = {}, {}, []
        for yol in md:
            sources[yol.name] = hash_metin(yol.read_text(encoding="utf-8"))
            ozet, bas = dosya_ozeti(yol)
            ozetler[yol.name] = ozet
            dosya_satirlari.append(dosya_satiri(yol.name, ozet, bas))
        subdirs = {cocuk.name: hash_metin(icerikler[cocuk]) for cocuk in alt_dizinler}
        alt_l0 = {cocuk.name: l0_tablosu[cocuk] for cocuk in alt_dizinler}
        alt_satirlari = [f"- `{ad}/` — {l0 or '(özet yok)'}" for ad, l0 in alt_l0.items()]
        l0 = l0_uret(dizin, ozetler, alt_l0)
        govde = govde_kur(dizin.name, l0, dosya_satirlari, alt_satirlari)
        goreli = dizin.relative_to(vault).as_posix()
        yeni = frontmatter(goreli, bugun, sources, subdirs) + govde
        hedef = dizin / OZET_ADI
        eski = hedef.read_text(encoding="utf-8") if hedef.is_file() else None
        mevcut = frontmatter_oku(eski) if eski is not None else None
        ayni = bool(mevcut) and mevcut["sources"] == sources and mevcut["subdirs"] == subdirs
        icerikler[dizin] = eski if ayni else yeni
        l0_tablosu[dizin] = l0
        plani.append({
            "dizin": goreli,
            "yol": hedef,
            "icerik": yeni,
            "durum": "guncel" if ayni else ("eksik" if eski is None else "eski"),
        })
    return plani


def build(vault: Path, dry_run: bool = False, tarih: str | None = None) -> dict:
    """Özetleri yapraktan köke üretir; hash değişmemişse dosyaya dokunmaz."""
    bugun = tarih or dt.date.today().isoformat()
    yenilenen, atlanan = [], 0
    for kayit in plan(vault, bugun):
        if kayit["durum"] == "guncel":
            atlanan += 1
            continue
        if not dry_run:
            atomik_yaz(kayit["yol"], kayit["icerik"])
        yenilenen.append(kayit["dizin"])
    return {"yenilendi": len(yenilenen), "atlandi": atlanan, "dizinler": yenilenen, "dry_run": dry_run}


def status(vault: Path, tarih: str | None = None) -> dict:
    """Eksik veya eski özetleri listeler."""
    kayitlar = plan(vault, tarih or dt.date.today().isoformat())
    return {
        "toplam": len(kayitlar),
        "eksik": [k["dizin"] for k in kayitlar if k["durum"] == "eksik"],
        "eski": [k["dizin"] for k in kayitlar if k["durum"] == "eski"],
        "guncel": sum(1 for k in kayitlar if k["durum"] == "guncel"),
    }


def show(vault: Path, dizin: str) -> str:
    """Bir dizinin özet dosyasını döndürür."""
    yol = (vault / dizin / OZET_ADI).resolve()
    if not yol.is_relative_to(vault.resolve()) or not yol.is_file():
        raise ValueError(f"özet bulunamadı: {dizin}")
    return yol.read_text(encoding="utf-8")


def harita(vault: Path, depth: int = 2) -> str:
    """Ajan açılışı için kök dizinlerin yalnız L0 satırlarından harita."""
    vault = vault.resolve()
    satirlar = []
    for dizin in sorted(dizinler(vault), key=lambda yol: yol.relative_to(vault).as_posix()):
        goreli = dizin.relative_to(vault).as_posix()
        if len(Path(goreli).parts) > depth:
            continue
        yol = dizin / OZET_ADI
        if not yol.is_file():
            continue
        satirlar.append(f"- `{goreli}/` — {l0_ayikla(yol.read_text(encoding='utf-8'))}")
    metin = "\n".join(satirlar) + ("\n" if satirlar else "")
    return metin + f"toplam: {len(metin)} karakter\n"


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Dizin özeti sidecar aracı")
    ayristirici.add_argument("--vault", type=Path, default=Path("."))
    alt = ayristirici.add_subparsers(dest="cmd", required=True)
    komut = alt.add_parser("build")
    komut.add_argument("--dry-run", action="store_true")
    alt.add_parser("status")
    komut = alt.add_parser("show")
    komut.add_argument("dizin")
    komut = alt.add_parser("map")
    komut.add_argument("--depth", type=int, default=2)
    secenek = ayristirici.parse_args(argv)
    vault = secenek.vault
    if secenek.cmd == "build":
        print(json.dumps(build(vault, secenek.dry_run), ensure_ascii=False))
    elif secenek.cmd == "status":
        print(json.dumps(status(vault), ensure_ascii=False))
    elif secenek.cmd == "show":
        sys.stdout.write(show(vault, secenek.dizin))
    else:
        sys.stdout.write(harita(vault, secenek.depth))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
