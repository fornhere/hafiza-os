"""Bounded optional procedure routing. Suggestions never replace mandatory rules."""
from pathlib import Path
import hashlib
import json
import jev_client
import hafiza

# Reviewed static summaries, not runtime text mined from arbitrary documents.
# Only these local paths can be recommended; the model cannot invent file paths.
PROCEDURES = (
 ('memory-policy','zihin/hafıza-sistemi.md','Kalıcı hafıza kaydı, tercih değişikliği, kaynak sürümü veya Mem0 senkronu yaparken kayıt politikasını oku. Basit geçmiş bilgi sorusu için gerekmez.'),
 ('maintenance','komuta/hafıza-konsolidasyonu.md','Bekleyen oturum/aday incelemesi, eksik kayıt, eski kaynak uzlaştırma ve arka plan hafıza bakımının işlem adımları.'),
 ('claim-check','HAFIZA-DONGUSU.md','Hafızaya dayalı bir kullanıcı tercihi veya karar iddiasını alıntı ve kaynakla doğrulama; kanıt desteği ve çelişki incelemesi. Genel kavram açıklaması için gerekmez.'),
 ('production','komuta/ajan-isletimi.md','Kapak, maskot veya video üretimi öncesinde kaynak ve referans denetimi; gerçek araç girdisi ve kullanıcı kabulünü ayırma. Sadece bir tercih sormak üretim değildir.'),
 ('release','YAYINLAMA.md','Hafıza sisteminin kod veya şablon düzeltmesini test edip GitHub sürümüne gönderme: manifest, temiz ağaç, yayın taraması ve uzak HEAD doğrulama.'),
 ('agent-setup','ENTEGRASYONLAR.md','Claude, Codex veya Antigravity için hafıza bağlantısı, hook kurulumu, istemci ayarı veya hook arızası teşhisi.'),
 ('agenda','zihin/açık-işler.md','Kullanıcı gündemi, ne kaldığını veya devam edilecek işleri soruyorsa güncel kaynaklı açık işleri seç. Başka net göreve eski işler ekleme.'),
)

def route(vault, query, budget=1000):
    vault=Path(vault)
    result=dict(text='',paths=[],source_versions={},advisory=True,mandatory_rules_unchanged=True)
    try: cfg=jev_client.load_config(vault)
    except (ValueError,OSError):
        result['diagnostics']=['config_invalid'];return result
    if jev_client.purpose_mode(cfg,'procedure_routing')=='off':return result
    # These files are local instructions, not user memory. Send only the bounded
    # reviewed descriptions and current request, never full files or secrets.
    if not isinstance(query,str) or hafiza.contains_secret(query):
        result['diagnostics']=['restricted_query'];return result
    candidates=[];versions={};by_id={}
    for ident,relative,description in PROCEDURES:
        try:
            path=hafiza.source_file(vault,relative)
            if not path.is_file():continue
            versions[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        except (ValueError,OSError):continue
        by_id[ident]=relative
        candidates.append(dict(id=ident,title=ident,statement=description,scope='procedure',domains=['procedure']))
    evaluation=jev_client.evaluate(vault,query,candidates,source_versions=versions,scope='procedure',purpose='procedure_routing')
    result['jev']=evaluation
    try:
        unchanged=all(hashlib.sha256(hafiza.source_file(vault,p).read_bytes()).hexdigest()==s for p,s in versions.items())
    except (ValueError,OSError):unchanged=False
    if not unchanged:
        result['diagnostics']=['source_changed'];return result
    if evaluation.get('degraded') or evaluation.get('mode')!='on':return result
    scores=evaluation.get('scores',{})
    order=sorted((i for i in by_id if scores.get(i,0)>=1.5),key=lambda i:(-scores[i],i))
    lines=['İşleme özel okuma önerisi (temel kurallar aynen geçerli):']
    for ident in order[:3]:
        relative=by_id[ident];line='- '+str(vault/relative)+' — yalnız görevle ilgili bölümü oku.'
        if len('\n'.join(lines+[line]))>max(0,budget):continue
        lines.append(line);result['paths'].append(relative);result['source_versions'][relative]=versions[relative]
    if result['paths']:result['text']='\n'.join(lines)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--vault',type=Path,required=True);p.add_argument('query')
    a=p.parse_args();print(json.dumps(route(a.vault,a.query),ensure_ascii=False,indent=2))
