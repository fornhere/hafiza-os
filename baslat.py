#!/usr/bin/env python3
"""Hafıza OS: indir, Obsidian'ı hazırla, ajanı ve isteğe bağlı API'leri bağla."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import warnings
import zipfile

API = 'https://api.github.com/repos/fornhere/hafiza-os'
OBSIDIAN_API = 'https://api.github.com/repos/obsidianmd/obsidian-releases/releases?per_page=10'


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Hafiza-OS-installer', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read(5_000_000))


def download(url, destination, digest=None, limit=600_000_000):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('İndirme HTTPS gerektirir.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Hafiza-OS-installer'})
    h = hashlib.sha256()
    size = 0
    created = False
    if destination.exists() or destination.is_symlink():
        raise ValueError('İndirme hedefi zaten var.')
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open('xb') as output:
            created = True
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError('İndirme boyut sınırını aştı.')
                output.write(chunk)
                h.update(chunk)
        if digest and digest != 'sha256:' + h.hexdigest():
            raise ValueError('İndirilen dosyanın SHA256 doğrulaması başarısız.')
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def safe_path(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError('Kurulum yolu sembolik bağlantı içeremez.')
    return path


def extract_source(archive, destination):
    with zipfile.ZipFile(archive) as z:
        rows = z.infolist()
        if not rows or sum(x.file_size for x in rows) > 100_000_000 or len(rows) > 10000:
            raise ValueError('Şablon arşivi boyutu geçersiz.')
        roots = set()
        claude_link = None
        names = set()
        for row in rows:
            name = PurePosixPath(row.filename)
            mode = row.external_attr >> 16
            allowed_link = (stat.S_ISLNK(mode) and len(name.parts) == 2 and name.parts[-1] == 'CLAUDE.md' and z.read(row) == b'agents.md')
            if allowed_link:
                claude_link = row.filename
            if (name.is_absolute() or '..' in name.parts or '\\' in row.filename or ':' in row.filename
                    or (stat.S_ISLNK(mode) and not allowed_link) or row.filename in names):
                raise ValueError('Güvensiz şablon arşivi.')
            roots.add(name.parts[0]); names.add(row.filename)
        if len(roots) != 1:
            raise ValueError('Şablon arşivi tek kök içermeli.')
        z.extractall(destination)
        source = destination / next(iter(roots))
        if not (source / 'araclar/ajan_kur.py').is_file() or not (source / 'agents.md').is_file():
            raise ValueError('İndirilen şablon eksik.')
        if claude_link:
            (source / 'CLAUDE.md').write_bytes((source / 'agents.md').read_bytes())
        return source


def asset_for(releases, system, machine):
    arm = machine.lower() in ('arm64', 'aarch64')
    if system == 'Linux' and machine.lower() not in ('x86_64', 'amd64', 'arm64', 'aarch64'):
        raise ValueError('Bu Linux mimarisi için otomatik Obsidian indirme desteklenmiyor.')
    suffix = {'Linux': '-arm64.AppImage' if arm else '.AppImage', 'Darwin': '.dmg', 'Windows': '.exe'}.get(system)
    if not suffix:
        raise ValueError('Bu işletim sistemi için Obsidian indirmesi desteklenmiyor.')
    for release in releases:
        if release.get('prerelease') or release.get('draft'):
            continue
        for asset in release.get('assets', []):
            name = asset['name']
            if not name.endswith(suffix) or (system == 'Linux' and not arm and '-arm64' in name):
                continue
            url = asset['browser_download_url']
            if not url.startswith('https://github.com/obsidianmd/obsidian-releases/releases/download/'):
                raise ValueError('Obsidian indirme kaynağı geçersiz.')
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', asset.get('digest') or ''):
                raise ValueError('Obsidian sağlama değeri bulunamadı.')
            return asset
    raise ValueError('Obsidian masaüstü indirmesi bulunamadı.')


def prepare_obsidian(app_dir, system=None, machine=None):
    system = system or platform.system()
    if shutil.which('obsidian') or (system == 'Darwin' and Path('/Applications/Obsidian.app').exists()):
        print('Obsidian zaten kurulu; tekrar indirilmedi.')
        return {'status': 'existing'}
    if system == 'Windows':
        for base in [os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles', '')]:
            if base and any((Path(base) / p).exists() for p in ['Obsidian/Obsidian.exe', 'Programs/Obsidian/Obsidian.exe']):
                print('Obsidian zaten kurulu; tekrar indirilmedi.')
                return {'status': 'existing'}
    asset = asset_for(get_json(OBSIDIAN_API), system, machine or platform.machine())
    app_dir = safe_path(app_dir); app_dir.mkdir(parents=True, exist_ok=True)
    name = asset['name']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('Obsidian dosya adı geçersiz.')
    target = app_dir / name
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ValueError('Obsidian hedefi geçersiz.')
        h = hashlib.sha256()
        with target.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        h = h.hexdigest()
        if 'sha256:' + h != asset['digest']:
            raise ValueError('Mevcut Obsidian dosyası sağlama değeriyle eşleşmiyor.')
    else:
        print('Obsidian resmi dağıtımı indiriliyor…', flush=True)
        download(asset['browser_download_url'], target, asset['digest'])
    if system == 'Linux':
        target.chmod(0o700)
    print('Obsidian dosyası hazır: ' + str(target))
    return {'status': 'downloaded', 'path': str(target), 'system': system}


def private_json(path, data):
    path = safe_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    if os.name == 'nt':
        # chmod does not provide a private Windows ACL.
        identity = subprocess.check_output(['whoami'], text=True).strip()
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', identity + ':F'], capture_output=True)
        if result.returncode:
            path.unlink()
            raise ValueError('Anahtar dosyasının Windows erişimi sınırlandırılamadı.')


def secret(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            value = getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            raise ValueError('Gizli giriş için gerçek bir terminal gerekli; anahtar kaydedilmedi.') from None
    if value and (len(value) > 4096 or any(c.isspace() for c in value) or any(ord(c) < 32 for c in value)):
        raise ValueError('Anahtar biçimi geçersiz; boşluk veya kontrol karakteri içeremez.')
    return value


def optional_services(vault, config_home):
    print('\nİsteğe bağlı bağlantılar — boş bırakıp Enter ile geçebilirsin.')
    print('Anahtar girersen ilgili hizmete sorgu içeriği gönderilebilir. Anahtarlar ekranda görünmez.')
    mem0 = secret('Mem0 API anahtarı [Enter: atla]: ')
    uid = None
    if mem0:
        uid = input('Mem0 kullanıcı kimliği [ben]: ').strip() or 'ben'
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', uid):
            raise ValueError('Mem0 kimliğinde yalnız harf, rakam, nokta, tire ve alt çizgi kullan.')
    jev = secret('Jev / TypeSafe API anahtarı [Enter: atla]: ')
    if not mem0 and not jev:
        return {'mem0': 'skipped', 'jev': 'skipped'}
    ident = hashlib.sha256(str(vault).encode()).hexdigest()[:16]
    keys_dir = safe_path(config_home) / 'hafiza-os' / ident
    if mem0:
        path = keys_dir / 'mem0.json'
        private_json(path, {'MEM0_API_KEY': mem0})
        private_json(vault / 'komuta/mem0.json', {'enabled': True, 'user_id': uid, 'credentials_file': str(path)})
    if jev:
        path = keys_dir / 'jev.json'
        private_json(path, {'TYPESAFE_API_KEY': jev})
        private_json(vault / 'komuta/jev.json', {'mode': 'on', 'model': 'jev-latest', 'provider': 'typesafe',
                     'base_url': 'https://api.typesafe.ai', 'credentials_file': str(path)})
    return {'mem0': 'configured_unverified' if mem0 else 'skipped',
            'jev': 'configured_unverified' if jev else 'skipped'}


def run(args):
    if sys.version_info < (3, 10):
        raise ValueError('Python 3.10 veya sonrası gerekli.')
    interactive = not args.non_interactive
    if interactive and not sys.stdin.isatty():
        raise ValueError('Kurucuyu terminalde çalıştır; otomasyon için --non-interactive kullan.')
    target = safe_path(args.vault)
    home = safe_path(args.client_home or Path.home())
    config_home = safe_path(args.config_home or home / '.config')
    if config_home == target or target in config_home.parents:
        raise ValueError('Anahtar dizini hafıza kasasının dışında olmalı.')
    if target.exists():
        raise ValueError(f'Hedef zaten var; üzerine yazılmadı: {target}. --vault ile yeni klasör seç.')
    agent = args.agent
    if not agent and interactive:
        agent = input('Kullandığın ajan [codex/claude/antigravity]: ').strip().lower()
    if agent not in ('codex', 'claude', 'antigravity'):
        raise ValueError('--agent codex, claude veya antigravity belirt.')
    revision = args.revision or get_json(API + '/commits/main')['sha']
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Kaynak sürümü geçersiz.')
    print('Hafıza dosyaları indiriliyor…', flush=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.hafiza-indir-', dir=target.parent) as tmp:
        temporary = Path(tmp)
        archive = temporary / 'source.zip'
        download('https://codeload.github.com/fornhere/hafiza-os/zip/' + revision, archive, limit=100_000_000)
        source = extract_source(archive, temporary / 'source')
        target.mkdir(mode=0o700)
        for child in source.iterdir():
            shutil.move(str(child), str(target / child.name))
    obsidian = {'status': 'skipped'}
    if not args.skip_obsidian:
        try:
            obsidian = prepare_obsidian(home / 'Applications' / 'Hafiza-OS')
        except (OSError, ValueError, KeyError) as error:
            obsidian = {'status': 'failed', 'reason': type(error).__name__}
            print('Obsidian indirilemedi; hafıza kurulumu devam ediyor. Resmi indirme: https://obsidian.md/download')
    services = optional_services(target, config_home) if interactive else {'mem0': 'skipped', 'jev': 'skipped'}
    command = [sys.executable, '-X', 'utf8', str(target / 'araclar/ajan_kur.py'), '--vault', str(target), '--agent', agent]
    if args.client_home:
        command += ['--home', str(home)]
        if agent == 'codex':
            command += ['--codex-home', str(home / '.codex')]
    print('Ajan bağlantısı kuruluyor…', flush=True)
    subprocess.run(command, check=True, capture_output=True, text=True)
    subprocess.run(command + ['--apply'], check=True, capture_output=True, text=True)
    report = {'source_revision': revision, 'agent': agent, 'obsidian': obsidian, 'services': services}
    private_json(target / 'komuta/kurulum-sonucu.json', report)
    print('\nKasa ve ajan yönerge bağlantısı hazır: ' + str(target))
    print('Obsidian → Open folder as vault → ' + str(target))
    if obsidian.get('path'):
        print('Obsidian dosyasını aç: ' + obsidian['path'])
        print('Windows/macOS: indirilen kurucunun uygulama kurulumunu tamamla.' if obsidian.get('system') != 'Linux' else 'Linux: AppImage dosyası çalıştırılabilir olarak hazırlandı.')
    for service, status in services.items():
        print(service + ': ' + ('atlandı' if status == 'skipped' else 'ayarlandı; API anahtarı henüz canlı doğrulanmadı'))
    print('Ajanı yeniden başlat, bu kasada yeni sohbet aç: agents.md dosyasını oku; profilimi birlikte hazırlayalım.')
    print('Otomatik sohbet kaydı ve arka plan incelemesi ayrıca kurulur: KULLANIM.md')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=['codex', 'claude', 'antigravity'])
    parser.add_argument('--vault', default='~/Hafiza')
    parser.add_argument('--revision', help='Kaynak commit SHA; varsayılan güncel main')
    parser.add_argument('--client-home', help='İzole test için istemci ayar kökü')
    parser.add_argument('--config-home', help='Anahtar dizininin üst klasörü; kasa dışında olmalı')
    parser.add_argument('--skip-obsidian', action='store_true')
    parser.add_argument('--non-interactive', action='store_true', help='API sorularını atla; --agent gerekir')
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError, KeyboardInterrupt, zipfile.BadZipFile) as error:
        # Anahtarlar ve sunucu cevapları hata çıktısına yazılmaz.
        print('Kurulum tamamlanmadı: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        print('Oluşmuş kasa silinmedi. Sorunu çözdükten sonra farklı --vault yolu kullanabilirsin.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
