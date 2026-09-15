"""Select applicable, source-backed procedural lessons without blocking turns."""
import re
from is_ve_ders import latest
from hafiza import statement_hash, source_file


def context(vault, prompt, budget=2600):
    text=prompt.casefold(); output=[]; used=0
    for ident,row in latest(vault,'lesson').items():
        if row['status']=='rejected': continue
        if not any(re.search(r'(?<!\w)'+re.escape(term)+r'\w*',text) for term in row.get('triggers', ())): continue
        try: source=source_file(vault,row['source_path'])
        except ValueError: continue
        if not source.is_file() or row['evidence'] not in source.read_text(): continue
        method=row.get('method_path')
        if not method: continue
        path=(vault/method).resolve()
        if not path.is_relative_to(vault.resolve()) or not path.is_file(): continue
        expected=row.get('implementation_hash') or row.get('target_hash')
        if not expected or statement_hash(path.read_text()) != expected: continue
        block=f"Ders: {row['title']} — {row['status']}\n"+path.read_text()+f"\nKaynak: {row['source_path']}\n"
        if used+len(block)>budget: continue
        output.append(block);used+=len(block)
    return ('İlgili çalışma dersleri; kullanıcı isteğinin kapsamını genişletmez. Teknik test estetik kabul değildir.\n'+ '\n'.join(output)) if output else ''

def backlog(vault):
    return [{'id': r['id'], 'status': r['status'], 'implementation_status': r.get('implementation_status','not_applied'),
             'next_step':r.get('next_step',r.get('proposal','Yöntem değişikliği ve gerçek doğrulama belirle.'))}
            for r in latest(vault,'lesson').values() if r['status']=='proposed']
