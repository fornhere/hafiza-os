"""Read-only output verification against configured project roots and review evidence."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import hafiza as h


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def review_binding(output):
    """Append this binding to the review report after actually checking the file."""
    stamp=dt.datetime.fromisoformat(output['verified_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('invalid_review_time')
    return dict(id=output['id'], path=str(Path(output['path']).resolve()), sha256=output['sha256'],
                reviewer=output['reviewer'], verified_at=stamp.astimezone(dt.timezone.utc).isoformat())


def checked_output(vault, project_id, output):
    if not isinstance(output, dict): raise ValueError('output_object_required')
    required = ('id','label','path','sha256','verified_at','reviewer',
                'verification_path','verification_sha256','verification_evidence')
    if any(not isinstance(output.get(k),str) or not output[k].strip() for k in required):
        raise ValueError('output_fields_required')
    if output.get('sensitivity','normal') != 'normal' or h.contains_secret(json.dumps(output,ensure_ascii=False)):
        raise ValueError('restricted_output')
    uses = output.get('uses',[])
    if not isinstance(uses,list) or any(not isinstance(x,str) or not x.strip() for x in uses):
        raise ValueError('invalid_uses')
    cfg=json.loads((vault/'komuta/gorev-baglam.json').read_text())
    projects=[p for p in cfg.get('projects',[]) if p.get('id')==project_id]
    if len(projects)!=1: raise ValueError('output_project_unresolved')
    path=Path(output['path'])
    roots=[Path(p).resolve() for p in projects[0].get('roots',[]) if Path(p).is_absolute()]
    if not path.is_absolute() or path.is_symlink() or not path.is_file(): raise ValueError('output_path_invalid')
    actual=path.resolve()
    if not any(actual.is_relative_to(root) and root!=Path(root.anchor) for root in roots):
        raise ValueError('output_outside_project')
    if file_digest(actual)!=output['sha256']: raise ValueError('output_revision_changed')
    relative=Path(output['verification_path'])
    if relative.is_absolute() or '..' in relative.parts: raise ValueError('unsafe_review_path')
    review=h.source_file(vault,str(relative));content=review.read_text()
    if h.contains_secret(content): raise ValueError('restricted_review')
    if file_digest(review)!=output['verification_sha256']: raise ValueError('review_revision_changed')
    if len(output['verification_evidence'])<20 or output['verification_evidence'] not in content:
        raise ValueError('review_evidence_missing')
    stamp=dt.datetime.fromisoformat(output['verified_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp>dt.datetime.now(dt.timezone.utc): raise ValueError('invalid_review_time')
    bindings=[]
    for line in content.splitlines():
        if line.startswith('output-review: '):
            try: bindings.append(json.loads(line[len('output-review: '):]))
            except ValueError: continue
    if review_binding(output) not in bindings: raise ValueError('review_not_bound_to_output')
    return dict(output,path=str(actual),project_id=project_id,uses=uses,
                verified_at=stamp.astimezone(dt.timezone.utc).isoformat())


def validate_outputs(vault, project_id, outputs):
    if not isinstance(outputs,list): raise ValueError('outputs_list_required')
    result=[checked_output(vault,project_id,o) for o in outputs]
    if len({o['id'] for o in result})!=len(result): raise ValueError('duplicate_output_id')
    return result


def verified_outputs(vault, project_id):
    from is_ve_ders import latest
    outputs=[];diagnostics=[]
    if not project_id:return dict(outputs=[],diagnostics=[])
    for row in latest(vault,'task').values():
        if row.get('project_id')!=project_id or row.get('status') not in {'active','blocked','done'}:continue
        if not row.get('outputs'):continue
        try:
            source=h.source_file(vault,row['source_path']);content=source.read_text()
            if not row.get('source_content_hash') or row['source_content_hash']!=h.statement_hash(content):
                raise ValueError('task_source_changed')
            if len(row.get('evidence',''))<10 or row['evidence'] not in content:raise ValueError('task_evidence_missing')
        except (ValueError,OSError,KeyError,TypeError):
            diagnostics.append('task_output_source_unverified');continue
        try:
            checked=validate_outputs(vault,project_id,row['outputs'])
            outputs.extend(dict(o,task_id=row['id']) for o in checked)
        except (ValueError,OSError,KeyError,TypeError):
            diagnostics.append('output_or_review_unverified')
    outputs.sort(key=lambda o:(o['verified_at'],o['task_id'],o['id']),reverse=True)
    return dict(outputs=outputs,diagnostics=diagnostics)


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--vault',type=Path,required=True);p.add_argument('--project',required=True)
    a=p.parse_args();print(json.dumps(verified_outputs(a.vault,a.project),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
