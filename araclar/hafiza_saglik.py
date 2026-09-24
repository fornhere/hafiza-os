"""Read-only operational health; timestamps never imply successful processing."""
import datetime as dt
import json
from pathlib import Path

import hafiza as memory

RUN_PATH = Path('gelen-kutusu/codex-oturumları/.state/maintenance.json')


def catalog_health(vault):
    """Global eligibility, before query/scope ranking; never return catalog text."""
    result = dict(status='unknown', active_count=None, eligible_count=None,
                  excluded_count=None, policy_excluded_count=None, source_blocked_count=None,
                  inactive_count=None, exclusion_reasons={})
    if not (vault / memory.CATALOG_PATH).exists():
        return result, []  # The catalog/Mem0 layer is optional.
    checks = []
    def check(name, status, reason):
        checks.append(dict(name=name, status=status, reason=reason, at=None))
    try:
        records = memory.load_catalog(vault)
        errors = memory.validate_catalog(vault, records)
        result['validation_error_count'] = len(errors)
        check('catalog_validation', 'failed' if errors else 'healthy',
              'Katalog şema, kaynak ve hash bütünlüğü hatalı.' if errors else
              'Katalog şema, kaynak ve hash bütünlüğü geçerli; erişilebilirlik ayrı kontrol edilir.')
        active = [row for row in records if row.get('status') == 'active']
        reasons = {}
        eligible = 0
        policy_excluded = 0
        source_blocked = 0
        for row in active:
            codes = set()
            if not memory.retrievable(row):
                code = ('sensitivity_restricted' if row.get('sensitivity', 'normal') != 'normal'
                        else 'validity_window_excluded')
                reasons[code] = reasons.get(code, 0) + 1
                policy_excluded += 1
                continue  # Match context: source eligibility is checked only after policy.
            row_errors = memory.context_record_errors(vault, row)
            for error in row_errors:
                # Only fixed, public reason codes may leave this function.
                code = str(error).rsplit(':', 1)[-1].strip()
                codes.add(code if code in {'source_revision_unreviewed', 'source_revision_changed',
                                           'source_binding_changed'} else 'record_integrity_error')
            if codes:
                source_blocked += 1
                for code in codes:
                    reasons[code] = reasons.get(code, 0) + 1
            else:
                eligible += 1
        excluded = len(active) - eligible
        result.update(status='failed' if errors or source_blocked else 'healthy',
                      active_count=len(active), eligible_count=eligible, excluded_count=excluded,
                      policy_excluded_count=policy_excluded, source_blocked_count=source_blocked,
                      inactive_count=len(records)-len(active), exclusion_reasons=reasons)
        check('retrieval_eligibility', 'failed' if source_blocked else 'healthy',
              f'Etkin kayıt: {len(active)}; erişime uygun: {eligible}; dışlanan: {excluded} '
              f'(politika: {policy_excluded}; kaynak: {source_blocked}). '
              'Kapsam ve sorgu sıralaması bu sayılara dahil değildir.' +
              (' Nedenler: ' + ', '.join(f'{code}={count}' for code, count in sorted(reasons.items()))
               if reasons else ''))
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        checks.clear()
        result['status'] = 'failed'
        check('catalog_validation', 'failed', 'Katalog veya kaynak doğrulama verisi okunamadı.')
        check('retrieval_eligibility', 'unknown', 'Katalog erişilebilirliği hesaplanamadı.')
    return result, checks


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
    settings = vault / 'komuta/hafıza-işletim.json'
    try:
        require_scheduled = settings.exists() and json.loads(settings.read_text()).get('require_scheduled_scan', False)
    except (ValueError, OSError, AttributeError):
        require_scheduled = False
        add('scheduler', 'failed', 'Zamanlayıcı kontrol ayarı okunamadı.')
    if require_scheduled:
        scheduled = vault / RUN_PATH.with_name('scheduled-scan.json')
        if not scheduled.exists():
            add('scheduler', 'unknown', 'Yeni sürümde zamanlanmış tarama henüz gözlenmedi; elle tarama bunun yerine geçmez.')
        else:
            try:
                data = json.loads(scheduled.read_text()); stamp = data['finished_at']
                state = 'failed' if data.get('status') != 'complete' else ('stale' if age(stamp) > 7200 else 'healthy')
                add('scheduler', state, 'Son zamanlanmış taramanın durumu; elle tarama bu saati yenilemez.', stamp)
            except (ValueError, KeyError, TypeError, OSError):
                add('scheduler', 'failed', 'Zamanlanmış tarama makbuzu okunamadı.')
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
    catalog, catalog_checks = catalog_health(vault)
    checks.extend(catalog_checks)
    from konsolidasyon import candidate_states
    states = candidate_states(vault, now)
    pending_ages = []
    for candidate in states['pending']:
        try:
            created = dt.datetime.fromisoformat(candidate['created_at'].replace('Z', '+00:00'))
            if created.tzinfo and created <= now:
                pending_ages.append((now - created).total_seconds())
        except (KeyError, TypeError, ValueError):
            continue
    candidate_queue = dict(pending_count=len(states['pending']), blocked_count=len(states['blocked']),
                           terminal_count=len(states['terminal']))
    add('candidate_queue', 'stale' if any(seconds > 86400 for seconds in pending_ages) else 'healthy',
        f"İncelenmemiş aday: {candidate_queue['pending_count']}; engellenen aday: {candidate_queue['blocked_count']}. " +
        ('İncelenmemiş aday 24 saatten eski.' if any(seconds > 86400 for seconds in pending_ages)
         else 'Engellenen adaylar tek başına sağlık hatası sayılmaz.'))
    rank = {'healthy': 0, 'unknown': 1, 'stale': 2, 'failed': 3}
    return dict(status=max((c['status'] for c in checks), key=rank.get),
                checked_at=now.isoformat(), checks=checks, catalog=catalog,
                candidate_queue=candidate_queue,
                limits='Veri hattı kontrolüdür; modelin uygulaması ve kullanıcı faydası ayrı ölçülür.')


def notice(vault):
    report = snapshot(vault)
    # Static catalog diagnostics belong in status, not every task's opening.
    # Runtime scan/scheduler/remote audit failures keep their existing notices.
    checks = [c for c in report['checks']
              if c['name'] not in {'catalog_validation', 'retrieval_eligibility'}]
    rank = {'healthy': 0, 'unknown': 1, 'stale': 2, 'failed': 3}
    status = max((c['status'] for c in checks), key=rank.get, default='healthy')
    if status == 'healthy':
        return ''
    return ('Hafıza işletim durumu: ' + status + '. ' + ' '.join(
        c['reason'] for c in checks if c['status'] != 'healthy') +
        ' Eski başarıyı güncel çalışma garantisi sayma; net kullanıcı görevini bölme.')
