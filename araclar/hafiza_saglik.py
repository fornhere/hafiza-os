"""Read-only operational health; timestamps never imply successful processing."""
import datetime as dt
import json
from pathlib import Path

RUN_PATH = Path('gelen-kutusu/codex-oturumları/.state/maintenance.json')


def snapshot(vault, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    checks = []
    def add(name, state, reason, at=None):
        checks.append(dict(name=name, status=state, reason=reason, at=at))
    def age(value):
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timezone required')
        elapsed = (now - stamp).total_seconds()
        if elapsed < -300:
            raise ValueError('future timestamp')
        return elapsed
    run = vault / RUN_PATH
    if not run.exists():
        add('capture', 'unknown', 'Henüz doğrulanmış tarama makbuzu yok.')
    else:
        try:
            data = json.loads(run.read_text())
            stamp = data.get('finished_at') or data['started_at']
            elapsed = age(stamp)
            if data['status'] == 'failed':
                add('capture', 'failed', data.get('error_code', 'scan_failed'), stamp)
            elif data.get('parse_errors', 0):
                add('capture', 'failed', 'Tanınmayan veya bozuk oturum kaynağı var.', stamp)
            elif data['status'] != 'complete':
                add('capture', 'failed' if elapsed > 600 else 'unknown', 'Tarama tamamlanmadı.', stamp)
            elif elapsed > 7200:
                add('capture', 'stale', 'Son başarılı tarama iki saatten eski.', stamp)
            elif data.get('oldest_eligible_at') and age(data['oldest_eligible_at']) > 86400:
                add('capture', 'stale', 'Uygun bekleyen sonuç 24 saatten eski.', stamp)
            else:
                add('capture', 'healthy', 'Tarama güncel; özetlerin doğruluğu ayrı inceleme gerektirir.', stamp)
        except (ValueError, KeyError, TypeError, OSError):
            add('capture', 'failed', 'Tarama makbuzu okunamadı.')
    directory = vault / 'günlük/hafıza-makbuzları'
    audits = sorted(directory.glob('*-audit-*.json'))
    if not audits:
        add('remote_audit', 'unknown', 'Uzak geri okuma makbuzu yok.')
    else:
        try:
            data = json.loads(audits[-1].read_text()); report = data['payload']
            elapsed = age(data['at'])
            fields = ('catalog_errors', 'missing_remote', 'drifted', 'orphan_remote_ids', 'duplicate_remote_groups')
            if any(report.get(k) for k in fields):
                add('remote_audit', 'failed', 'Uzak kayıt denetiminde fark veya bütünlük hatası var.', data['at'])
            elif any(k not in report for k in fields):
                add('remote_audit', 'unknown', 'Eksik denetim şeması.', data['at'])
            else:
                add('remote_audit', 'stale' if elapsed > 86400 else 'healthy',
                    'Denetim 24 saatten eski.' if elapsed > 86400 else 'Son uzak doğrulama güncel.', data['at'])
        except (ValueError, KeyError, TypeError, OSError):
            add('remote_audit', 'failed', 'Denetim makbuzu okunamadı.')
    rank = {'healthy': 0, 'unknown': 1, 'stale': 2, 'failed': 3}
    return dict(status=max((c['status'] for c in checks), key=rank.get),
                checked_at=now.isoformat(), checks=checks,
                limits='Veri hattı kontrolüdür; modelin uygulaması ve kullanıcı faydası ayrı ölçülür.')


def notice(vault):
    report = snapshot(vault)
    if report['status'] == 'healthy':
        return ''
    return ('Hafıza işletim durumu: ' + report['status'] + '. ' + ' '.join(
        c['reason'] for c in report['checks'] if c['status'] != 'healthy') +
        ' Eski başarıyı güncel çalışma garantisi sayma; net kullanıcı görevini bölme.')
