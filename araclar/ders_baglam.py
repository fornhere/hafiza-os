"""Select applicable, source-backed procedural lessons without blocking turns."""
from is_ve_ders import latest, is_instruction_target, has_user_acceptance
from hafiza import statement_hash, source_file


# A conservative verb vocabulary, not a Turkish stemmer. Unknown words still
# get the existing noun matching, but cannot acquire unrestricted prefix matching.
_VERB_ROOTS = frozenset('aktar başlat bitir bırak çalış çarp değiştir denetle '
    'durdur düzenle ekle getir gizle göster hazırla incele kaldır kapat '
    'kullan paylaş serp söndür yükle'.split())
_DERIVATIONS = ('lı', 'li', 'lu', 'lü', 'lık', 'lik', 'luk', 'lük')


def _trigger_roots(term):
    from gorev_baglam import _SUFFIXES
    roots = {term}
    if term in _VERB_ROOTS:
        return roots
    # Strip only one listed nominal ending, which may itself be compound
    # (sekmeyi -> sekme, sekmelerimizi -> sekme). Never shorten to <=3 letters.
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term)-len(suffix) > 3:
            root = term[:-len(suffix)]
            roots.add(root)
            if suffix[0] in 'aeıioöuü' and root[-1] in 'bcdğ':
                roots.add(root[:-1]+{'b': 'p', 'c': 'ç', 'd': 't', 'ğ': 'k'}[root[-1]])
    return roots


def trigger_match(trigger, words):
    """Lesson-only expansion; multiword triggers retain alias_match semantics.

    Single words support bounded nominal roots, existing synonym groups, one
    derivation, and prefix matching for known verb roots. This is lexical matching: it
    does not infer intent, disambiguate senses or treat negation as exclusion.
    """
    from gorev_baglam import alias_match, inflected, query_words, _SYNONYMS
    parts = query_words(trigger)
    if len(parts) != 1:
        return alias_match(trigger, words)
    term = parts[0]
    if len(term) <= 3:
        return term in words
    if term in _VERB_ROOTS and any(word.startswith(term) for word in words):
        return True
    roots = _trigger_roots(term)
    for group in _SYNONYMS:
        if any(inflected(member, term) for member in group):
            roots.update(group)
    for base in roots:
        for word in words:
            if inflected(base, word):
                return True
            if len(base) <= 3:
                continue
            if any(inflected(base+suffix, word) for suffix in _DERIVATIONS):
                return True
    return False


def context(vault, prompt, budget=2600, project_id=None, workflow_ids=()):
    return context_details(vault,prompt,budget,project_id,workflow_ids)['text']


def _integrity(vault, row):
    if any(is_instruction_target(vault,row.get(k)) for k in ('target_path','method_path')) and (row.get('status')!='verified' or not has_user_acceptance(row)):
        return 'instruction_target_unaccepted'
    if row.get('verification_hash'):
        from bilgi_agi import digest
        try:
            verification=source_file(vault,row['verification_path'])
            if digest(verification)!=row['verification_hash']: return 'verification_changed'
        except (ValueError,OSError,KeyError): return 'verification_changed'
    try: content=source_file(vault,row['source_path']).read_text()
    except (ValueError,OSError,KeyError): return 'source_changed'
    # Legacy lessons require explicit re-review through put; never auto-pin.
    if not row.get('source_content_hash'): return 'legacy_unreviewed'
    if row['source_content_hash']!=statement_hash(content) or 'evidence' not in row or row['evidence'] not in content: return 'source_changed'
    method=row.get('method_path')
    if not method: return 'method_missing'
    try: path=source_file(vault,method)
    except (ValueError,OSError): return 'method_missing'
    expected=row.get('implementation_hash') or row.get('target_hash')
    try:
        if not expected or statement_hash(path.read_text())!=expected: return 'method_changed'
    except (ValueError,OSError): return 'method_changed'
    return None


def context_details(vault, prompt, budget=2600, project_id=None, workflow_ids=()):
    """Project-owned lessons require matching project or explicitly selected workflow.

    Legacy rows with neither scope nor project_id retain their global behavior.
    New scoped rows should use project_id (or scope='project:<id>'); explicit
    scope='global' is appropriate only for methods intended for every project.
    A project_id is never overridden by a global scope label.
    """
    from gorev_baglam import query_words
    header="İlgili çalışma dersleri; kullanıcı isteğinin kapsamını genişletmez. Teknik test estetik kabul değildir.\n"
    words=query_words(prompt); output=[]; lessons=[]; diagnostics=[]; used=len(header)
    for ident,row in sorted(latest(vault,'lesson').items()):
        if row['status']=='rejected': continue
        if row.get('outcome_id') and row['status']!='verified' and 'review_required' not in row: continue
        allowed={project_id, *workflow_ids} - {None}
        owner=row.get('project_id')
        scope=row.get('scope', 'global' if not owner else 'project:'+owner)
        if owner and owner not in allowed: continue
        if scope not in {'global','user'} and not (scope.startswith('project:') and scope[8:] in allowed): continue
        if not any(trigger_match(term,words) for term in row.get('triggers', ())): continue
        reason='review_required' if 'review_required' in row else _integrity(vault,row)
        if reason:
            diagnostics.append(dict(id=ident,reason=reason)); continue
        try: method=source_file(vault,row['method_path']).read_text()
        except (ValueError,OSError):
            diagnostics.append(dict(id=ident,reason='method_changed')); continue
        block=f"Ders: {row['title']} — {row['status']}\n"+method+f"\nKaynak: {row['source_path']}\n"
        if row.get('observed_result'): block+='Gözlenen sonuç: '+row['observed_result']+' (genel başarı iddiası değildir).\n'
        if row.get('conditions'): block+='Koşul: '+row['conditions']+'\n'
        if row.get('proposal'): block+='Doğrulanmış ders: '+row['proposal']+'\n'
        if used+len(block)+(1 if output else 0)>budget:
            diagnostics.append(dict(id=ident,reason='budget')); continue
        used+=len(block)+(1 if output else 0);output.append(block)
        lessons.append(dict(id=row['id'],version=row.get('version'),status=row['status']))
    return dict(text=(header+'\n'.join(output)) if output else '',lessons=lessons,diagnostics=diagnostics)

def backlog(vault):
    output=[]
    for r in latest(vault,'lesson').values():
        if r['status']=='rejected': continue
        reason=_integrity(vault,r)
        if r['status']!='proposed' and not reason: continue
        entry=dict(id=r['id'],status=r['status'],implementation_status=r.get('implementation_status','not_applied'),
                   next_step=r.get('next_step',r.get('proposal','Yöntem değişikliği ve gerçek doğrulama belirle.')))
        if r['status']=='proposed' and 'review_required' in r:
            review=r['review_required'];entry['review_required']=review
            entry['next_step']=f"Fayda incelemesi: zarar {review['harm']} > yardım {review['help']}; dersi yeniden incele (otomatik silinmedi)."
        if reason:
            entry['recheck_reason']=reason
            if r['status']=='verified':
                entry['next_step']=f"Yeniden kontrol: {reason}. Kaynağı/yöntemi incele ve yeni sürümü is_ve_ders put ile bağla; o zamana kadar bağlama alınmaz."
        if any(is_instruction_target(vault,r.get(k)) for k in ('target_path','method_path')):
            entry['instruction_target']=True
            if reason=='instruction_target_unaccepted':
                entry['next_step']='Boşluk not edildi, uygulanmadı: talimat dosyası değişikliği kullanıcı kabulü (özgün kullanıcı mesajı alıntısı) ister.'
        output.append(entry)
    return output
