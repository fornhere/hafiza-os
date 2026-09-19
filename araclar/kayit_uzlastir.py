#!/usr/bin/env python3
"""Reviewed repair of blocked legacy records, not new preference promotion.

Semantic entailment remains the reviewer's responsibility. Historical source
summaries are explicitly marked and never treated as a new user endorsement.
Prepared/applied events preserve interrupted transactions for investigation.
"""
import argparse
import copy
import datetime as dt
import json
import uuid
from pathlib import Path
import hafiza

AUDIT = Path("günlük/kayit-uzlastirma.jsonl")

@hafiza.serialized
def reconcile(vault, data, apply=False):
    path = vault / hafiza.CATALOG_PATH
    catalog_hash = hafiza.statement_hash(path.read_text(encoding="utf-8"))
    if data.get("expected_catalog_hash") != catalog_hash:
        raise ValueError("catalog revision changed")
    rows = hafiza.load_catalog(vault)
    row = next((r for r in rows if r["memory_id"] == data.get("memory_id")), None)
    if row is None:
        raise ValueError("record not found")
    expected_error = row["memory_id"] + ":source_revision_unreviewed"
    if (row["status"] != "active" or row.get("source_content_hash") or
            hafiza.context_record_errors(vault, row) != [expected_error]):
        raise ValueError("only blocked legacy records are eligible")
    if row["sensitivity"] != "normal" or hafiza.contains_secret(row["statement"]):
        raise ValueError("private or secret record")
    if data.get("reviewed_by") != "codex-consolidator" or data.get("semantic_reviewed") is not True:
        raise ValueError("separate semantic reviewer required")
    if data.get("expected_statement") != row["statement"]:
        raise ValueError("statement changed")
    source = hafiza.source_file(vault, row["source_path"])
    content = source.read_text(encoding="utf-8")
    source_hash = hafiza.statement_hash(content)
    if data.get("expected_source_hash") != source_hash:
        raise ValueError("source revision changed")
    reason, evidence = data.get("reason", ""), data.get("evidence", "")
    if not isinstance(reason, str) or len(reason) < 30 or hafiza.contains_secret(reason):
        raise ValueError("review reason required")
    if not isinstance(evidence, str) or len(evidence) < 10 or evidence not in content or hafiza.contains_secret(evidence):
        raise ValueError("exact source evidence required")
    action = data.get("action")
    new = copy.deepcopy(row)
    if action == "narrow":
        statement = data.get("statement", "")
        if (not isinstance(statement, str) or len(statement) < 10 or
                len(statement) >= len(row["statement"]) or hafiza.contains_secret(statement)):
            raise ValueError("shorter non-secret statement required")
        # Scope/subject/type/date are deliberately not accepted as input changes.
        anchor = data.get("source_anchor", "")
        if not isinstance(anchor, str) or len(anchor) < 5 or anchor not in content:
            raise ValueError("exact source anchor required")
        new.update(statement=statement, source_hash=hafiza.statement_hash(statement),
                   source_content_hash=source_hash, source_anchor=anchor,
                   evidence=evidence, evidence_hash=hafiza.statement_hash(evidence))
        new["confidence"] = "legacy-source-summary-reviewed"
    elif action == "quarantine":
        if "statement" in data:
            raise ValueError("quarantine cannot rewrite statement")
        new["status"] = "quarantined"
    else:
        raise ValueError("action must be narrow or quarantine")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    new["legacy_review"] = dict(at=now, reviewed_by=data["reviewed_by"], reason=reason,
        source_content_hash=source_hash, evidence=evidence,
        limitation="Historical source summary review; no new user endorsement or original-message verification.")
    changed = [new if r["memory_id"] == row["memory_id"] else r for r in rows]
    errors = hafiza.validate_catalog(vault, changed)
    if errors:
        raise ValueError("invalid catalog: " + "; ".join(errors))
    result = dict(result="planned", before=row, after=new, mem0_sync_required=True,
                  source_hash=source_hash, catalog_before_hash=catalog_hash)
    if not apply:
        return result
    transaction_id = str(uuid.uuid4())
    event = dict(transaction_id=transaction_id, at=now, action=action,
                 reviewed_by=data["reviewed_by"], before=row, after=new,
                 catalog_before_hash=catalog_hash, source_hash=source_hash,
                 mem0_sync_required=True)
    hafiza._append_jsonl(vault / AUDIT, dict(event, phase="prepared"))
    # Refuse a source edit that occurred during the review transaction.
    if hafiza.statement_hash(source.read_text(encoding="utf-8")) != source_hash:
        raise ValueError("source revision changed during transaction")
    hafiza._write_jsonl(path, changed)
    readback = hafiza.load_catalog(vault)
    if readback != changed:
        raise ValueError("catalog readback mismatch; transaction incomplete")
    after_hash = hafiza.statement_hash(path.read_text(encoding="utf-8"))
    hafiza._append_jsonl(vault / AUDIT, dict(event, phase="applied", catalog_after_hash=after_hash))
    result.update(result="applied", transaction_id=transaction_id, catalog_after_hash=after_hash,
                  audit_path=str(vault / AUDIT))
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, required=True)
    p.add_argument("--input-json", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    try:
        result = reconcile(args.vault.resolve(), json.loads(args.input_json.read_text(encoding="utf-8")), args.apply)
    except (ValueError, OSError) as exc:
        p.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
