"""Select applicable, source-backed procedural lessons without blocking turns."""
import re
from is_ve_ders import latest
from hafiza import statement_hash, source_file


def context(vault, prompt, budget=2600, project_id=None, workflow_ids=()):
    """Project-owned lessons require matching project or explicitly selected workflow.

    Legacy rows with neither scope nor project_id retain their global behavior.
    New scoped rows should use project_id (or scope='project:<id>'); explicit
    scope='global' is appropriate only for methods intended for every project.
    A project_id is never overridden by a global scope label.
    """
    from gorev_baglam import alias_match, query_words
    header="İlgili çalışma dersleri; kullanıcı isteğinin kapsamını genişletmez. Teknik test estetik kabul değildir.\n"
    text=prompt.casefold(); output=[]; used=len(header)
    for ident,row in sorted(latest(vault,'lesson').items()):
        if row['status']=='rejected': continue
        allowed={project_id, *workflow_ids} - {None}
        owner=row.get('project_id')
        scope=row.get('scope', 'global' if not owner else 'project:'+owner)
        if owner and owner not in allowed: continue
        if scope not in {'global','user'} and not (scope.startswith('project:') and scope[8:] in allowed): continue
        if not any(alias_match(term,query_words(text)) for term in row.get('triggers', ())): continue
        try: source=source_file(vault,row['source_path'])
        except ValueError: continue
        if not source.is_file(): continue
        content = source.read_text()
        # Legacy lessons require explicit re-review through put; never auto-pin.
        if not row.get('source_content_hash') or row['source_content_hash'] != statement_hash(content): continue
        if row['evidence'] not in content: continue
        method=row.get('method_path')
        if not method: continue
        path=(vault/method).resolve()
        if not path.is_relative_to(vault.resolve()) or not path.is_file(): continue
        expected=row.get('implementation_hash') or row.get('target_hash')
        if not expected or statement_hash(path.read_text()) != expected: continue
        block=f"Ders: {row['title']} — {row['status']}\n"+path.read_text()+f"\nKaynak: {row['source_path']}\n"
        if used+len(block)+(1 if output else 0)>budget: continue
        used+=len(block)+(1 if output else 0);output.append(block)
    return (header+'\n'.join(output)) if output else ''

def backlog(vault):
    return [{'id': r['id'], 'status': r['status'], 'implementation_status': r.get('implementation_status','not_applied'),
             'next_step':r.get('next_step',r.get('proposal','Yöntem değişikliği ve gerçek doğrulama belirle.'))}
            for r in latest(vault,'lesson').values() if r['status']=='proposed']
