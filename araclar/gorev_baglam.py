"""Local, source-validated task context. No network and no memory writes."""
import hashlib
import json
import re
from pathlib import Path
import hafiza as h
from is_ve_ders import brief

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tokens(text):
    return set(re.findall(r"[^\W_]+", text.casefold()))

def config(vault):
    path = vault / 'komuta/gorev-baglam.json'
    try: return json.loads(path.read_text()) if path.exists() else {'projects': []}
    except (ValueError,OSError): return {'projects': [], 'invalid': True}

def validate_asset(asset, actual_paths=None):
    path = Path(asset['path']).resolve()
    roots = [Path(p).resolve() for p in asset.get('allowed_roots', [])]
    if not roots or not any(path.is_relative_to(p) for p in roots):
        raise ValueError('asset outside approved roots')
    if asset.get('status') != 'approved' or not path.is_file():
        raise ValueError('asset missing or not approved')
    source = Path(asset.get('approval_source', ''))
    evidence = asset.get('approval_evidence', '')
    if not any(source.resolve().is_relative_to(p) for p in roots):
        raise ValueError('approval source outside approved roots')
    if len(evidence) < 10 or not source.is_file() or evidence not in source.read_text():
        raise ValueError('asset approval evidence missing')
    if digest(path) != asset.get('sha256'):
        raise ValueError('asset hash changed')
    if actual_paths is not None and path not in {Path(p).resolve() for p in actual_paths}:
        raise ValueError('approved asset absent from actual tool inputs')
    return path

def validate_inputs(assets, actual_paths, role='identity'):
    required = [a for a in assets if a.get('role') == role]
    if not required: raise ValueError('required asset role missing')
    return [str(validate_asset(a, actual_paths)) for a in required]

def build_task_package(vault, query, cwd=None, budget=5000):
    vault = Path(vault).resolve(); words = tokens(query)
    selected=[]; omitted=[]; lines=[]; used=0; assets=[]; source_versions={}
    projects=[]
    cfg=config(vault)
    if cfg.get('invalid'): omitted.append('config_invalid')
    for project in cfg.get('projects', []):
        explicit = any(tokens(alias) <= words for alias in project.get('aliases', []) if tokens(alias))
        location = cwd and any(Path(cwd).resolve().is_relative_to(Path(p).resolve()) for p in project.get('roots', []))
        if explicit or location: projects.append(project)
    project = projects[0] if len(projects)==1 else None
    scope = 'project:'+project['id'] if project else 'user'
    def add(ident, text):
        nonlocal used
        if used+len(text)>budget: omitted.append(ident+':budget'); return False
        lines.append(text); selected.append(ident); used+=len(text); return True
    if len(projects)>1:
        omitted.append('ambiguous_project')
        add('ambiguous_project','Birden fazla proje eşleşti; proje seçimini netleştirmeden dosya veya onay uydurma.')
    for row in h.load_catalog(vault):
        if not h.retrievable(row,scope): continue
        if not words.intersection(tokens(row.get('statement',''))): continue
        if h.validate_catalog(vault,[row]): omitted.append(row.get('memory_id','unknown')+':invalid'); continue
        if add(row['memory_id'],row['statement']+' (kaynak: '+row['source_path']+')'):
            source_versions[row['source_path']]=digest(h.source_file(vault,row['source_path']))
    if project:
        add('project', 'Proje: '+project['id'])
        for issue in project.get('unresolved',[]): add('unresolved', 'Teyit gerekli: '+issue)
        for ref in project.get('working_sources',[]):
            path=Path(ref['path']).resolve()
            if path.is_file():
                source_versions[str(path)]=digest(path)
                add('working-source',ref['role']+': '+str(path)+'; kaynak: '+ref['evidence_source']+'. Güncel içeriği aç; dosya varlığı kullanıcı kabulü değildir.')
            else: omitted.append(str(path)+':missing')
        for working_root in project.get('roots',[]): add('working-root','Çalışma kökü: '+working_root+'; devam etmeden canlı Git HEAD/status ve ilgili testleri doğrula.')
        for task in brief(vault,limit=100):
            if task.get('project_id')==project['id'] or task['id'] in project.get('task_ids',[]):
                add(task['id'],task['title']+': '+task['next_step']+' (kaynak: '+task['source_path']+')')
        for asset in project.get('assets',[]):
            try: path=validate_asset(asset)
            except (ValueError,OSError,KeyError) as e: omitted.append(asset.get('id','asset')+':'+str(e)); continue
            if add(asset['id'], 'Onaylı '+asset['role']+': '+str(path)+'; hash: '+asset['sha256']+'. Gerçek araç girdisini validate_inputs ile doğrula; dosyanın bulunması kullanıldığını kanıtlamaz.'): assets.append(asset)
        if words.intersection({'devam','dün','önceki','kaldık','hatırla'}):
            for relative in sorted(project.get('episode_sources',[]), key=lambda p: len(words & tokens(p)), reverse=True)[:3]:
                try:
                    path=h.source_file(vault,relative)
                    text=path.read_text()
                    if h.contains_secret(text): continue
                    source_versions[relative]=digest(path)
                    add(relative,'Tarihli geçmiş, güncel dosya yerine geçmez: '+relative+'\n'+text[:700]+'\n[Kaynak özeti kesilmiş olabilir; karar için tam kaynağı aç.]')
                except (OSError,ValueError): omitted.append(relative+':missing')
    from ders_baglam import context
    methods=context(vault,query,budget=max(0,budget-used))
    if methods: add('methods',methods)
    if assets:
        instruction='Üretim öncesi gorev_baglam.py package ile bu paketi al; gerçek araca gönderilecek referans yollarını JSON dizisi yapıp validate-inputs --package <paket.json> --actual-inputs <yollar.json> çalıştır. Bu denetim araç çağrısının otomatik gözlemcisi değildir; gerçek argümanlarla aynı yollar olmalı.'
        instruction += ' Paket varlık rolleri: '+', '.join(sorted({a['role'] for a in assets}))+'. validate-inputs için ilgili --role değerini kullan.'
        if not add('input-check',instruction):
            omitted.append('input-check:budget')
    errors=[reason for reason in omitted if not reason.endswith(':budget')]
    if errors: lines.append('Bağlam kontrolü: '+ '; '.join(errors)+'. Eksik veya değişmiş kaynağı onaylı sayma.')
    result={'project_id':project['id'] if project else None,'assets':assets,'source_versions':source_versions,'selected_ids':selected,'omitted_reasons':omitted,'text':'\n'.join(lines)}
    result['package_id']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return result


def hydrate_remote(vault, results, scope='user'):
    """Remote search ranks IDs; current canonical rows supply all content."""
    rows = {r['memory_id']: r for r in h.load_catalog(vault)}
    output=[]
    for item in results:
        ident=(item.get('metadata') or {}).get('memory_id')
        row=rows.get(ident)
        if row and h.retrievable(row,scope) and not h.validate_catalog(vault,[row]):
            output.append({'memory':row['statement'],'metadata':row})
    return output

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--vault',type=Path,default=Path(__file__).resolve().parents[1])
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('package');p.add_argument('query');p.add_argument('--cwd')
    p=sub.add_parser('validate-inputs');p.add_argument('--package',type=Path,required=True);p.add_argument('--actual-inputs',type=Path,required=True);p.add_argument('--role',default='identity')
    args=parser.parse_args()
    if args.command=='package': result=build_task_package(args.vault,args.query,args.cwd)
    else: result={'validated':validate_inputs(json.loads(args.package.read_text())['assets'],json.loads(args.actual_inputs.read_text()),args.role)}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
