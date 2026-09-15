"""Ephemeral asset-use validation; deliberately never writes memory or logs."""
import argparse
import hashlib
import json
from pathlib import Path
from gorev_baglam import validate_inputs


def prepare_image(package, args, role='identity'):
    """Validate then return the same argument object for an explicit call gate."""
    if not isinstance(args,dict) or not isinstance(args.get('prompt'),str) or not args['prompt'].strip():
        raise ValueError('nonempty image prompt required')
    if args.get('num_last_images_to_include') is not None:
        raise ValueError('explicit approved paths required; recent images are ambiguous')
    paths=args.get('referenced_image_paths')
    if not isinstance(paths,list) or not paths or not all(isinstance(p,str) for p in paths):
        raise ValueError('explicit image reference paths required')
    validate_inputs(package.get('assets',[]),paths,role=role)
    return args


def observe(package, transcript, call_id, session_id, role='identity'):
    """Read one rollout-owned invocation. Never evaluate wrapper code or copy text."""
    raw = Path(transcript).read_bytes()
    rows = []
    for line in raw.decode('utf-8').splitlines():
        try: rows.append(json.loads(line))
        except (ValueError, TypeError):
            raise ValueError('malformed transcript; usage cannot be verified')
    meta = next((r.get('payload', {}) for r in rows if r.get('type') == 'session_meta'), {})
    if meta.get('id') != session_id or meta.get('source') not in ('cli', 'vscode'):
        raise ValueError('rollout ownership does not match main session')
    items = [r.get('payload', {}) for r in rows if r.get('type') == 'response_item']
    calls = [p for p in items if p.get('call_id') == call_id and
             p.get('type') in ('function_call', 'custom_tool_call')]
    if len(calls) != 1:
        raise ValueError('call identity missing or ambiguous')
    call = calls[0]
    outputs = [p for p in items if p.get('call_id') == call_id and
               p.get('type') in ('function_call_output', 'custom_tool_call_output')]
    result = {'project_id': package.get('project_id'), 'call_id': call_id,
              'transcript_sha256': hashlib.sha256(raw).hexdigest(),
              'input_check': 'unknown', 'execution_evidence': 'unknown',
              'tool_result': 'present_unclassified' if outputs else 'not_observed',
              'technical_outcome': 'unknown', 'user_acceptance': 'unknown', 'persisted': False}
    # Structured error flags are negative evidence; output existence is not success.
    for out in outputs:
        value = out.get('output')
        if isinstance(value, str):
            try: value = json.loads(value)
            except ValueError: value = None
        if isinstance(value, dict) and value.get('isError') is True:
            result['tool_result'] = 'reported_error'
    name = call.get('name'); namespace = call.get('namespace')
    direct_imagegen = name == 'image_gen__imagegen' or (name == 'imagegen' and namespace == 'image_gen')
    if not direct_imagegen:
        result['reason'] = 'wrapper_or_unsupported_tool'
        return result
    if call.get('type') != 'function_call':
        result['reason'] = 'non_json_tool_input'
        return result
    args = call.get('arguments')
    try:
        args = json.loads(args) if isinstance(args, str) else args
    except ValueError:
        result['reason'] = 'invalid_arguments'
        return result
    if not isinstance(args, dict):
        result['reason'] = 'invalid_arguments'
        return result
    paths = args.get('referenced_image_paths')
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        result['reason'] = 'recent_images_without_paths' if args.get('num_last_images_to_include') else 'no_explicit_reference_paths'
        return result
    if args.get('num_last_images_to_include'):
        result['reason'] = 'ambiguous_reference_mechanism'
        return result
    # A referenced path in comments, prompt text or another call never counts.
    try:
        matched = validate_inputs(package.get('assets', []), paths, role=role)
    except (ValueError, OSError, KeyError):
        result.update(input_check='failed', reason='asset_validation_failed')
        return result
    result.update(input_check='passed', execution_evidence='recorded_tool_arguments', asset_count=len(matched))
    return result


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
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--invocation',type=Path); mode.add_argument('--transcript',type=Path)
    mode.add_argument('--image-arguments',type=Path)
    p.add_argument('--call-id'); p.add_argument('--session-id'); p.add_argument('--role',default='identity')
    p.add_argument('--outcome',type=Path)
    a=p.parse_args()
    if a.image_arguments:
        result=prepare_image(json.loads(a.package.read_text()),json.loads(a.image_arguments.read_text()),a.role)
    elif a.transcript:
        if not a.call_id or not a.session_id: p.error('transcript mode requires --call-id and --session-id')
        result=observe(json.loads(a.package.read_text()),a.transcript,a.call_id,a.session_id,a.role)
    else:
        result=check(json.loads(a.package.read_text()),json.loads(a.invocation.read_text()),
            json.loads(a.outcome.read_text()) if a.outcome else None)
    print(json.dumps(result,ensure_ascii=False))
