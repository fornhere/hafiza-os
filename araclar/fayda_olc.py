"""Compare labeled real-task observations; never invent missing measurements."""
import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(rows):
    groups = {}; identities = set()
    for row in rows:
        required = ('task_id','condition','workflow','model','protocol_version','outcome','evidence_source')
        if any(not row.get(k) for k in required):
            raise ValueError('observation identity, protocol and evidence source required')
        if row['condition'] not in ('A','B','C') or row['outcome'] not in ('accepted','rejected','abandoned','unknown'):
            raise ValueError('invalid condition/outcome')
        key = (row['task_id'],row['condition'])
        if key in identities: raise ValueError('duplicate task observation')
        identities.add(key)
        for field in ('repeat_explanations','correction_rounds','elapsed_seconds','maintenance_seconds'):
            value = row.get(field)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                raise ValueError('invalid measurement: '+field)
        group_key = (row['workflow'],row['model'],row['protocol_version'],row['condition'])
        groups.setdefault(group_key,[]).append(row)
    output=[]
    for (workflow,model,protocol,condition), tasks in sorted(groups.items()):
        counts={outcome:sum(t['outcome']==outcome for t in tasks) for outcome in ('accepted','rejected','abandoned','unknown')}
        result=dict(workflow=workflow,model=model,protocol_version=protocol,condition=condition,
                    tasks=len(tasks),outcomes=counts,measurements={})
        for field in ('repeat_explanations','correction_rounds','elapsed_seconds','maintenance_seconds'):
            values=[t[field] for t in tasks if t.get(field) is not None]
            result['measurements'][field]=dict(observed=len(values),missing=len(tasks)-len(values),
                total=sum(values) if values else None,median=statistics.median(values) if values else None)
        output.append(result)
    return dict(status='no_observations' if not rows else 'descriptive_only',groups=output,
                conclusion='Henüz fayda sonucu yok.' if not rows else
                'Ham sayımlar; koşullar ve görev zorluğu eşlenmeden nedensel kazanım iddia edilmez. Başarısız işler dahil.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--observations',type=Path,required=True)
    a=p.parse_args();rows=[json.loads(line) for line in a.observations.read_text().splitlines() if line.strip()]
    print(json.dumps(summarize(rows),ensure_ascii=False,indent=2))
