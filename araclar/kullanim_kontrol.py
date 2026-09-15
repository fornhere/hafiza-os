"""Ephemeral asset-use validation; deliberately never writes memory or logs."""
import argparse
import hashlib
import json
from pathlib import Path
from gorev_baglam import validate_inputs


def check(package, invocation, outcome=None):
    if not invocation.get('tool') or not invocation.get('call_id'):
        raise ValueError('tool and call_id required')
    paths = invocation.get('actual_paths')
    if not isinstance(paths, list) or not all(isinstance(p,str) for p in paths):
        raise ValueError('actual tool input paths required')
    validated = validate_inputs(package.get('assets', []), paths, role=invocation.get('required_role','identity'))
    # Caller-supplied arguments alone are a preflight, not evidence of execution.
    trace = invocation.get('trace')
    observed = False
    if trace:
        source = Path(trace['path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != trace['sha256']:
            raise ValueError('tool trace changed')
        needle = trace.get('evidence','')
        if len(needle)<20 or needle not in source.read_text():
            raise ValueError('tool trace evidence missing')
        event = json.loads(needle)
        if event.get('call_id') != invocation['call_id'] or event.get('tool') != invocation['tool'] or event.get('actual_paths') != paths:
            raise ValueError('tool trace does not match invocation')
        observed = True
    outcome = outcome or {}
    # Separate declarations; neither file presence nor tool invocation implies acceptance.
    technical = outcome.get('technical', 'unknown')
    accepted = outcome.get('user', 'unknown')
    if technical not in ('unknown','passed','failed') or accepted not in ('unknown','accepted','rejected'):
        raise ValueError('invalid outcome')
    return {'project_id':package.get('project_id'), 'input_check':'passed',
            'asset_count':len(validated), 'execution_evidence':'trace_matched' if observed else 'preflight_only',
            'technical_declaration':technical, 'user_declaration':accepted,
            'persisted':False}


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--package',type=Path,required=True)
    p.add_argument('--invocation',type=Path,required=True); p.add_argument('--outcome',type=Path)
    a=p.parse_args()
    print(json.dumps(check(json.loads(a.package.read_text()),json.loads(a.invocation.read_text()),
        json.loads(a.outcome.read_text()) if a.outcome else None),ensure_ascii=False))
