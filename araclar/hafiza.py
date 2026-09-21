#!/usr/bin/env python3
"""Obsidian kanonik hafıza kataloğu için doğrulama araçları."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import functools
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from platform_lock import exclusive_lock

CATALOG_PATH = Path("zihin/hafıza-kataloğu.jsonl")
CANDIDATE_PATH = Path("gelen-kutusu/hafıza-adayları.jsonl")
EVENT_PATH = Path("günlük/hafıza-olayları.jsonl")
DEFAULT_USER_ID = os.environ.get("HAFIZA_MEM0_USER_ID", "kullanici")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:api[_ -]?key|token|parola|şifre)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
REQUIRED_FIELDS = {
    "memory_id",
    "kind",
    "scope",
    "subject_key",
    "statement",
    "status",
    "source_path",
    "source_anchor",
    "source_hash",
    "observed_at",
    "valid_from",
    "valid_to",
    "confidence",
    "sensitivity",
    "mem0_id",
    "supersedes",
    "reviewed_by",
    "schema_version",
}
VALID_KINDS = {"semantic", "episodic", "procedural", "working"}
VALID_STATUSES = {"active", "quarantined", "superseded", "deleted"}
VALID_SENSITIVITIES = {"normal", "private", "secret"}


def serialized(function):
    """Canonical local writers share one lock; sync holds it only at prepare/commit."""
    @functools.wraps(function)
    def wrapped(vault, *args, **kwargs):
        directory = vault / "günlük" / "hafıza-makbuzları"
        directory.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(directory / ".writer.lock"):
            return function(vault, *args, **kwargs)
    return wrapped


def source_file(vault: Path, relative: str) -> Path:
    path = (vault / relative).resolve()
    if not path.is_relative_to(vault.resolve()) or not path.is_file():
        raise ValueError("kaynak kasa içinde mevcut bir dosya olmalı")
    return path


def resolve_user_id(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return os.environ.get("HAFIZA_MEM0_USER_ID") or DEFAULT_USER_ID


def statement_hash(statement: str) -> str:
    return "sha256:" + hashlib.sha256(statement.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: kayıt nesne değil")
        records.append(value)
    return records


def load_catalog(vault: Path) -> list[dict[str, Any]]:
    return load_jsonl(vault / CATALOG_PATH)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values
    )
    temp.write_text(payload, encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


@serialized
def add_candidate(
    vault: Path,
    *,
    statement: str,
    kind: str,
    scope: str,
    subject_key: str,
    source_path: str,
    source_anchor: str,
    confidence: str,
    sensitivity: str,
    proposed_by: str,
    evidence: str | None = None,
    evidence_source: dict | None = None,
    rationale: str | None = None,
    conditions: str | None = None,
) -> dict[str, Any]:
    if contains_secret(statement):
        raise ValueError("aday gizli bilgi içeriyor")
    if sensitivity != "normal":
        raise ValueError("aday kuyruğu yalnız normal duyarlılık kabul eder")
    if kind not in VALID_KINDS or not statement.strip() or not subject_key.strip():
        raise ValueError("geçersiz aday alanları")
    if evidence is not None:
        if not 10 <= len(evidence) <= 1500 or contains_secret(evidence):
            raise ValueError("geçersiz veya gizli kaynak kanıtı")
        if evidence not in source_file(vault, source_path).read_text(encoding="utf-8"):
            raise ValueError("kanıt kaynak dosyada bulunamadı")
    if evidence_source is not None:
        from capture_source import validate_candidate_evidence
        validate_candidate_evidence(vault, evidence_source.get("session_id"), evidence_source, evidence_source, evidence)
    for name, value in (("rationale", rationale), ("conditions", conditions)):
        if value is not None and (not isinstance(value, str) or len(value.strip()) < 10 or value not in source_file(vault, source_path).read_text(encoding="utf-8") or contains_secret(value)):
            raise ValueError(name + " kaynakta aynen bulunmalı")
    normalized = " ".join(statement.casefold().split())
    for existing in load_jsonl(vault / CANDIDATE_PATH):
        if (
            existing.get("scope", "user") == scope
            and " ".join(str(existing.get("statement", "")).casefold().split()) == normalized
        ):
            return {"result": "duplicate", "candidate_id": existing["candidate_id"]}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    candidate = {
        "candidate_id": str(uuid.uuid4()),
        "statement": statement.strip(),
        "kind": kind,
        "scope": scope,
        "subject_key": subject_key,
        "source_path": source_path,
        "source_anchor": source_anchor,
        "confidence": confidence,
        "sensitivity": sensitivity,
        "proposed_by": proposed_by,
        "status": "pending",
        "created_at": now,
        "schema_version": 1,
    }
    for name, value in (("rationale", rationale), ("conditions", conditions)):
        if value is not None: candidate[name] = value
    if evidence is not None:
        candidate["evidence"] = evidence
        candidate["evidence_hash"] = statement_hash(evidence)
    candidate["source_content_hash"] = statement_hash(source_file(vault, source_path).read_text(encoding="utf-8"))
    if evidence_source is not None:
        candidate["evidence_source"] = evidence_source
    _append_jsonl(vault / CANDIDATE_PATH, candidate)
    _append_jsonl(
        vault / EVENT_PATH,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "candidate.queued",
            "candidate_id": candidate["candidate_id"],
            "at": now,
            "actor": proposed_by,
            "schema_version": 1,
        },
    )
    return {"result": "queued", "candidate_id": candidate["candidate_id"]}


def assess_candidate(
    candidate: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    normalized = " ".join(str(candidate["statement"]).casefold().split())
    for record in records:
        if record.get("status") != "active":
            continue
        if record.get("scope", "user") != candidate.get("scope", "user"):
            continue
        current = " ".join(str(record.get("statement", "")).casefold().split())
        if current == normalized:
            return {"result": "duplicate", "duplicate_of": record.get("memory_id")}
        if record.get("subject_key") == candidate.get("subject_key"):
            return {"result": "conflict", "conflicts_with": record.get("memory_id")}
        # Cross-key overlap is a review warning, never an automatic semantic verdict.
        from gorev_baglam import content_words, word_match, inflected
        ignored = ("kullanıcı", "tercih", "eder", "ister", "istiyor", "istiyorum", "kullanır", "kullanıyor")
        def concepts(text):
            text = text.casefold().replace("arka plan", "zemin").replace("karanlık", "koyu")
            return {w for w in content_words(text) if not any(inflected(i, w) for i in ignored)}
        a, b = concepts(candidate["statement"]), concepts(record.get("statement", ""))
        overlap = sum(any(word_match(x,y) for y in b) for x in a)
        if min(len(a),len(b)) >= 2 and overlap >= 2 and overlap / max(1,min(len(a),len(b))) >= 0.6:
            return {"result": "needs_semantic_review", "related_to": record.get("memory_id"),
                    "reason": "Farklı anahtarda benzer konu; tekrar/çelişki insan veya kaynak incelemesi gerektirir."}
    return {"result": "eligible"}


@serialized
def promote_candidate(
    vault: Path,
    candidate_id: str,
    *,
    memory_id: str,
    reviewed_by: str | None,
    apply: bool = False,
    supersedes: str | None = None,
) -> dict[str, Any]:
    if not reviewed_by:
        raise ValueError("terfi için inceleyen kimliği gerekir")
    candidates = load_jsonl(vault / CANDIDATE_PATH)
    candidate = next((item for item in candidates if item.get("candidate_id") == candidate_id), None)
    if candidate is None:
        raise ValueError("aday bulunamadı")
    events = load_jsonl(vault / EVENT_PATH)
    if any(
        event.get("event_type") in ("candidate.promoted", "candidate.rejected", "candidate.duplicate")
        and event.get("candidate_id") == candidate_id
        for event in events
    ):
        raise ValueError("aday daha önce terfi ettirilmiş veya kapatılmış")
    records = load_catalog(vault)
    if any(r["memory_id"] == memory_id for r in records):
        raise ValueError("memory_id zaten var")
    source = source_file(vault, candidate["source_path"])
    if candidate.get("evidence") is not None:
        evidence = candidate["evidence"]
        if statement_hash(evidence) != candidate.get("evidence_hash") or evidence not in source.read_text(encoding="utf-8"):
            raise ValueError("kaynak kanıtı değişmiş veya kayıp")
    if candidate.get("source_content_hash") and statement_hash(source.read_text(encoding="utf-8")) != candidate["source_content_hash"]:
        raise ValueError("adayın kaynak sürümü değişmiş; yeniden incele")
    for field in ("rationale", "conditions"):
        value = candidate.get(field)
        if value is not None and (not isinstance(value,str) or len(value.strip())<10 or value not in source.read_text(encoding="utf-8") or contains_secret(value)):
            raise ValueError("karar gerekçesi veya koşulu kaynakla eşleşmiyor")
    if candidate.get("evidence_source"):
        from capture_source import validate_candidate_evidence
        origin = candidate["evidence_source"]
        validate_candidate_evidence(vault, origin.get("session_id"), origin, origin, candidate.get("evidence"))
    elif reviewed_by == "codex-consolidator" and candidate.get("kind") == "semantic":
        raise ValueError("otomatik terfi için özgün kullanıcı mesajı kanıtı gerekli")
    if candidate.get("sensitivity") != "normal" or contains_secret(candidate["statement"]):
        raise ValueError("özel veya gizli aday terfi edemez")
    assessment = assess_candidate(candidate, records)
    if assessment["result"] != "eligible" and not (
        assessment["result"] == "conflict" and supersedes
    ):
        raise ValueError(f"aday terfi edemez: {assessment['result']}")
    if supersedes and (assessment.get("conflicts_with") != supersedes):
        raise ValueError("supersedes çelişen etkin kayıtla eşleşmeli")
    observed = str(candidate.get("created_at", ""))[:10] or dt.date.today().isoformat()
    record = {
        "memory_id": memory_id,
        "kind": candidate["kind"],
        "scope": candidate["scope"],
        "subject_key": candidate["subject_key"],
        "statement": candidate["statement"],
        "status": "active",
        "source_path": candidate["source_path"],
        "source_anchor": candidate["source_anchor"],
        "source_hash": statement_hash(candidate["statement"]),
        "observed_at": observed,
        "valid_from": observed,
        "valid_to": None,
        "confidence": candidate["confidence"],
        "sensitivity": candidate["sensitivity"],
        "mem0_id": None,
        "supersedes": supersedes,
        "reviewed_by": reviewed_by,
        "schema_version": 1,
    }
    record["source_content_hash"] = statement_hash(source.read_text(encoding="utf-8"))
    for field in ("evidence", "evidence_hash", "evidence_source", "rationale", "conditions"):
        if field in candidate: record[field] = candidate[field]
    if not apply:
        return {"result": "planned", "record": record}
    for old in records:
        if old["memory_id"] == supersedes:
            old["status"] = "superseded"
            old["valid_to"] = observed
    errors = validate_catalog(vault, records + [record])
    if errors:
        raise ValueError("terfi geçersiz: " + "; ".join(errors))
    _write_jsonl(vault / CATALOG_PATH, records + [record])
    _append_jsonl(
        vault / EVENT_PATH,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "candidate.promoted",
            "candidate_id": candidate_id,
            "memory_id": memory_id,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "actor": reviewed_by,
            "schema_version": 1,
        },
    )
    return {"result": "promoted", "record": record}


def memory_metadata(vault: Path, record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "memory_id",
        "kind",
        "scope",
        "subject_key",
        "status",
        "source_path",
        "source_hash",
        "schema_version",
        "observed_at",
        "valid_from",
        "valid_to",
        "confidence",
        "sensitivity",
        "reviewed_by",
        "supersedes",
    )
    metadata = {key: record.get(key) for key in keys}
    metadata.update(
        {
            "source": "obsidian",
            "vault_path": vault.name,
            "block_id": record.get("source_anchor"),
        }
    )
    return metadata


def sync_existing(vault, records, client, *, apply=False):
    """Serialize index workers, but never hold the canonical lock over network.

    Prepare and commit are short writer transactions. An intervening catalog
    change rejects the whole stale write; remote identity metadata permits repair
    on the next explicit sync without blindly adding another remote record.
    """
    from codex_hafiza import atomic
    vault = Path(vault)
    directory = vault / 'günlük/hafıza-makbuzları'
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(directory / '.sync.lock'):
        working = json.loads(json.dumps(records))
        journal = directory / 'sync-transactions' / (str(uuid.uuid4()) + '.json')
        @serialized
        def prepare(vault):
            before = load_catalog(vault)
            if apply and (vault/CATALOG_PATH).exists() and before != working:
                raise ValueError('katalog eşzamanlı değişmiş; yeniden yükleyip senkronu tekrarla')
            errors = validate_catalog(vault, working)
            if errors: raise ValueError('katalog geçersiz: ' + '; '.join(errors))
            if apply:
                atomic(journal, json.dumps(dict(status='prepared',
                    catalog_sha256=statement_hash(json.dumps(before,sort_keys=True)),
                    at=dt.datetime.now(dt.timezone.utc).isoformat())))
            return before
        before = prepare(vault)
        try:
            result = _sync_remote(vault, working, client, apply=apply)
        except Exception:
            if apply: atomic(journal, json.dumps(dict(status='remote_outcome_unknown',
                reconciliation_required=True)))
            raise
        @serialized
        def finish(vault):
            conflict = apply and load_catalog(vault) != before
            if conflict:
                result.update(verified=0, reconciliation_required=True, status='catalog_conflict')
            else:
                if apply and result.pop('catalog_changed', False):
                    _write_jsonl(vault/CATALOG_PATH, working)
                result.update(status='applied' if apply else 'preview', reconciliation_required=False)
                if apply: records[:] = working
            result.pop('catalog_changed', None)
            if apply: atomic(journal, json.dumps(dict(status=result['status'],
                reconciliation_required=result['reconciliation_required'],
                verified=result['verified'], total=result['total'])))
            return result
        return finish(vault)


def _sync_remote(
    vault: Path,
    records: list[dict[str, Any]],
    client: Any,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    errors = validate_catalog(vault, records)
    if errors:
        raise ValueError("katalog geçersiz: " + "; ".join(errors))
    remote = {item["id"]: item for item in client.list_memories()}
    receipt = {
        "apply": apply,
        "total": len(records),
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "missing_remote": 0,
        "verified": 0,
    }
    catalog_changed = False
    for record in records:
        if record["sensitivity"] != "normal" or contains_secret(record["statement"]):
            raise ValueError(f"{record['memory_id']}: gizli bilgi senkronlanamaz")
        if record["status"] in {"deleted", "superseded"} and not record.get("mem0_id"):
            receipt["skipped"] += 1
            continue
        memory_id = record.get("mem0_id")
        if not memory_id:
            matches = [item for item in remote.values() if
                       (item.get("metadata") or {}).get("memory_id") == record["memory_id"]
                       and (item.get("metadata") or {}).get("source") == "obsidian"
                       and (item.get("metadata") or {}).get("vault_path") == vault.name]
            if len(matches) > 1:
                raise ValueError("aynı memory_id için birden çok uzak kayıt var")
            if matches:
                memory_id = matches[0]["id"]
                if apply:
                    record["mem0_id"] = memory_id
                    catalog_changed = True
        current = remote.get(memory_id)
        if not memory_id:
            if record["status"] != "active":
                receipt["skipped"] += 1
                continue
            receipt["added"] += 1
            if apply:
                created = client.add_memory(record["statement"], memory_metadata(vault, record))
                record["mem0_id"] = created["id"]
                memory_id = created["id"]
                remote[memory_id] = created
                catalog_changed = True
                # Remote identity metadata recovers an interrupted local binding.
                # Local publication occurs once, under a revision-checked lock.
            continue
        if current is None:
            receipt["missing_remote"] += 1
            continue
        expected_metadata = memory_metadata(vault, record)
        current_metadata = current.get("metadata") or {}
        metadata_matches = all(current_metadata.get(k) == v for k, v in expected_metadata.items())
        needs_update = current.get("memory") != record["statement"] or not metadata_matches
        if needs_update:
            receipt["updated"] += 1
            if apply:
                client.update_memory(
                    memory_id,
                    record["statement"],
                    expected_metadata,
                    expiration_date=record.get("valid_to"),
                )
        else:
            receipt["unchanged"] += 1
    verified_remote = {item["id"]: item for item in client.list_memories()}
    for record in records:
        memory_id = record.get("mem0_id")
        current = verified_remote.get(memory_id)
        if current is None:
            continue
        expected_metadata = memory_metadata(vault, record)
        current_metadata = current.get("metadata") or {}
        if current.get("memory") == record["statement"] and all(
            current_metadata.get(k) == v for k, v in expected_metadata.items()
        ):
            receipt["verified"] += 1
    receipt["catalog_changed"] = catalog_changed
    return receipt


def audit(vault: Path, records: list[dict[str, Any]], client: Any) -> dict[str, Any]:
    errors = validate_catalog(vault, records)
    remote_items = client.list_memories()
    remote = {item["id"]: item for item in remote_items}
    linked_ids = {record.get("mem0_id") for record in records if record.get("mem0_id")}
    missing_remote: list[str] = []
    drifted: list[str] = []
    for record in records:
        memory_id = record.get("mem0_id")
        if not memory_id:
            continue
        current = remote.get(memory_id)
        if current is None:
            missing_remote.append(record["memory_id"])
            continue
        expected_metadata = memory_metadata(vault, record)
        current_metadata = current.get("metadata") or {}
        if current.get("memory") != record["statement"] or any(
            current_metadata.get(key) != value for key, value in expected_metadata.items()
        ):
            drifted.append(record["memory_id"])
    groups: dict[str, list[str]] = {}
    for item in remote_items:
        normalized = " ".join(str(item.get("memory", "")).casefold().split())
        groups.setdefault(normalized, []).append(item["id"])
    duplicate_groups = [ids for ids in groups.values() if len(ids) > 1]
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "local_count": len(records),
        "remote_count": len(remote_items),
        "catalog_errors": errors,
        "missing_remote": sorted(missing_remote),
        "drifted": sorted(drifted),
        "orphan_remote_ids": sorted(set(remote) - linked_ids),
        "duplicate_remote_groups": duplicate_groups,
        "status_counts": status_counts,
    }


def retrievable(metadata: dict[str, Any], scope: str | None = None) -> bool:
    if metadata.get("status") != "active" or metadata.get("sensitivity", "normal") != "normal":
        return False
    if scope is not None and metadata.get("scope") not in {"user", scope}:
        return False
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    # ISO dates sort chronologically; reject malformed validity dates.
    for field in ("valid_from", "valid_to"):
        value = metadata.get(field)
        if value:
            try:
                date = dt.date.fromisoformat(str(value)[:10]).isoformat()
            except ValueError:
                return False
            if field == "valid_from" and date > today:
                return False
            if field == "valid_to" and date <= today:
                return False
    return True


def context_from_results(
    results, *, query, scope, limit=5, char_budget=1200, records=None
):
    lines = []
    selected_ids = []
    canonical = {
        str(record.get("memory_id")): record
        for record in (records or [])
        if record.get("memory_id")
    }
    for item in results:
        metadata = dict(item.get("metadata") or {})
        if not retrievable(metadata, scope):
            continue
        memory_id = metadata.get("memory_id") or item.get("id", "unknown")
        record = canonical.get(str(memory_id), {})
        for field in ("rationale", "conditions"):
            if not metadata.get(field) and record.get(field):
                metadata[field] = record[field]
        source = metadata.get("source_path", "kaynak-yok")
        block = metadata.get("block_id", "")
        suffix = f"#{block}" if block else ""
        details = "".join(
            f" {label}: {metadata[field]}"
            for field, label in (("rationale", "Gerekçe"), ("conditions", "Geçerlilik koşulu"))
            if isinstance(metadata.get(field), str) and metadata[field].strip()
        )
        line = (
            f"- [{memory_id}] {item.get('memory', '')}{details} "
            f"(kaynak: {source}{suffix}; tarih: {metadata.get('observed_at', 'bilinmiyor')}; "
            f"güven: {metadata.get('confidence', 'bilinmiyor')})"
        )
        if len("\n".join(lines + [line])) > char_budget:
            continue
        lines.append(line); selected_ids.append(str(memory_id))
        if len(lines) >= limit:
            break
    return dict(query=query, scope=scope, included=len(lines), memory_ids=selected_ids,
                char_budget=char_budget, text="\n".join(lines))


def build_context_package(
    client: Any,
    *,
    query: str,
    scope: str,
    limit: int = 5,
    char_budget: int = 1200,
    user_id: str | None = None,
    threshold: float = 0.1,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    results = client.search_memories(
        query,
        filters={"user_id": resolve_user_id(user_id)},
        top_k=max(limit * 3, limit),
        threshold=threshold,
    )
    return context_from_results(
        results,
        query=query,
        scope=scope,
        limit=limit,
        char_budget=char_budget,
        records=records,
    )


def evaluate_retrieval(
    client: Any,
    cases: list[dict[str, Any]],
    *,
    user_id: str | None = None,
    threshold: float = 0.1,
) -> dict[str, Any]:
    resolved_user_id = resolve_user_id(user_id)
    details: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        results = client.search_memories(
            case["query"],
            filters={"user_id": resolved_user_id},
            top_k=int(case.get("top_k", 5)),
            threshold=float(case.get("threshold", threshold)),
        )
        latencies.append((time.perf_counter() - started) * 1000)
        found = [
            str((item.get("metadata") or {}).get("memory_id"))
            for item in results
            if retrievable(item.get("metadata") or {}, case.get("scope", "user"))
        ]
        expected = set(case.get("expected_memory_ids", []))
        forbidden = set(case.get("forbidden_memory_ids", []))
        passed = expected.issubset(found) and forbidden.isdisjoint(found)
        package = context_from_results(results, query=case["query"], scope=case.get("scope", "user"),
            limit=int(case.get("top_k", 5)), char_budget=int(case.get("char_budget", 1200)))
        context_ids = set(package["memory_ids"])
        details.append(
            {
                "id": case["id"],
                "passed": passed,
                "found": found,
                "missing": sorted(expected - set(found)),
                "forbidden_found": sorted(forbidden.intersection(found)),
                "context_passed": expected.issubset(context_ids) and forbidden.isdisjoint(context_ids),
                "context_missing": sorted(expected - context_ids),
            }
        )
    passed_count = sum(1 for item in details if item["passed"])
    total = len(details)
    return {
        "total": total,
        "passed": passed_count,
        "failed": total - passed_count,
        "accuracy": passed_count / total if total else 0.0,
        "context_passed": sum(1 for item in details if item["context_passed"]),
        "context_accuracy": sum(1 for item in details if item["context_passed"]) / total if total else 0.0,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "details": details,
    }


def evaluation_passes(report: dict[str, Any], *, minimum_accuracy: float = 0.9) -> bool:
    accuracy = float(report.get("accuracy", 0.0))
    return accuracy >= minimum_accuracy and float(report.get("context_accuracy", accuracy)) >= minimum_accuracy


def forget_remote(
    record: dict[str, Any],
    client: Any,
    *,
    approved_by: str | None,
    apply: bool = False,
) -> dict[str, Any]:
    if not approved_by:
        raise ValueError("uzak silme açık onay gerektirir")
    memory_id = record.get("mem0_id")
    if not memory_id:
        return {"result": "not-linked", "memory_id": record.get("memory_id")}
    if not apply:
        return {"result": "planned", "mem0_id": memory_id, "approved_by": approved_by}
    client.delete_memory(memory_id)
    remaining = {item["id"] for item in client.list_memories()}
    if memory_id in remaining:
        raise RuntimeError("silme doğrulanamadı")
    return {"result": "deleted", "mem0_id": memory_id, "approved_by": approved_by}


def validate_catalog(vault: Path, records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    memory_ids: set[str] = set()
    mem0_ids: set[str] = set()
    for index, record in enumerate(records, 1):
        missing = sorted(REQUIRED_FIELDS - record.keys())
        if missing:
            errors.append(f"kayıt {index}: eksik alanlar: {', '.join(missing)}")
            continue
        memory_id = str(record["memory_id"])
        if memory_id in memory_ids:
            errors.append(f"kayıt {index}: yinelenen memory_id: {memory_id}")
        memory_ids.add(memory_id)
        mem0_id = record.get("mem0_id")
        if mem0_id:
            if mem0_id in mem0_ids:
                errors.append(f"kayıt {index}: yinelenen mem0_id: {mem0_id}")
            mem0_ids.add(mem0_id)
        if record["kind"] not in VALID_KINDS:
            errors.append(f"{memory_id}: geçersiz kind")
        if record["status"] not in VALID_STATUSES:
            errors.append(f"{memory_id}: geçersiz status")
        if record["sensitivity"] not in VALID_SENSITIVITIES:
            errors.append(f"{memory_id}: geçersiz sensitivity")
        if record["schema_version"] != 1:
            errors.append(f"{memory_id}: desteklenmeyen schema_version")
        statement = str(record["statement"])
        if record["source_hash"] != statement_hash(statement):
            errors.append(f"{memory_id}: source_hash uyuşmuyor")
        source = (vault / str(record["source_path"])).resolve()
        if not source.is_relative_to(vault.resolve()) or not source.is_file():
            errors.append(f"{memory_id}: kaynak yok: {record['source_path']}")
        elif record.get("source_content_hash") and statement_hash(source.read_text(encoding="utf-8")) != record["source_content_hash"]:
            if not current_source_binding(vault, record, source.read_text(encoding="utf-8")):
                errors.append(f"{memory_id}: source_revision_changed")
    return errors


SOURCE_BINDINGS = Path("zihin/kaynak-surumleri.jsonl")


def current_source_binding(vault, record, content):
    bindings = [b for b in load_jsonl(vault / SOURCE_BINDINGS)
                if b.get("memory_id") == record["memory_id"]]
    if not bindings: return False
    b = bindings[-1]
    return (b.get("source_path") == record["source_path"]
            and b.get("statement_hash") == statement_hash(record["statement"])
            and b.get("source_content_hash") == statement_hash(content)
            and len(b.get("evidence", "")) >= 10 and b.get("evidence") in content
            and bool(b.get("reviewed_by")))


def context_record_errors(vault, record):
    """Schema integrity and current local source revision are separate checks.

    Legacy records need an explicitly reviewed binding, or their exact statement
    still present in the source. A present file alone is never enough.
    """
    errors = validate_catalog(vault, [record])
    if errors: return errors
    source = source_file(vault, record["source_path"])
    content = source.read_text(encoding="utf-8")
    expected = record.get("source_content_hash")
    if expected:
        if statement_hash(content) != expected and not current_source_binding(vault, record, content):
            return [record["memory_id"] + ":source_revision_changed"]
        return []
    bindings = [b for b in load_jsonl(vault / SOURCE_BINDINGS)
                if b.get("memory_id") == record["memory_id"]]
    if bindings:
        binding = bindings[-1]
        valid = (binding.get("source_path") == record["source_path"]
                 and binding.get("statement_hash") == statement_hash(record["statement"])
                 and binding.get("source_content_hash") == statement_hash(content)
                 and binding.get("evidence") in content
                 and len(binding.get("evidence", "")) >= 10)
        return [] if valid else [record["memory_id"] + ":source_binding_changed"]
    if record["statement"] in content:
        return []
    return [record["memory_id"] + ":source_revision_unreviewed"]


@serialized
def bind_source(vault, data, apply=False):
    """Attach a reviewed source version without rewriting a canonical statement.

    Exact evidence and revision are mechanical checks; entailment is explicitly
    the reviewer's responsibility. No automatic bulk pinning of stale sources.
    """
    row = next((r for r in load_catalog(vault) if r["memory_id"] == data.get("memory_id")), None)
    if row is None: raise ValueError("kayıt bulunamadı")
    if not data.get("reviewed_by") or len(data.get("reason", "")) < 20:
        raise ValueError("kaynak inceleyen ve gerekçe gerekli")
    source = source_file(vault, row["source_path"])
    content = source.read_text(encoding="utf-8")
    evidence = data.get("evidence", "")
    if len(evidence) < 10 or evidence not in content or contains_secret(evidence):
        raise ValueError("kaynakta bulunan açık kanıt gerekli")
    current_hash = statement_hash(content)
    if data.get("expected_source_hash") != current_hash:
        raise ValueError("incelenen kaynak sürümü değişti")
    record = dict(memory_id=row["memory_id"], source_path=row["source_path"],
                  statement_hash=statement_hash(row["statement"]), source_content_hash=current_hash,
                  evidence=evidence, reviewed_by=data["reviewed_by"], reason=data["reason"],
                  at=dt.datetime.now(dt.timezone.utc).isoformat())
    if apply: _append_jsonl(vault / SOURCE_BINDINGS, record)
    return {"result": "bound" if apply else "planned", "binding": record}


class Mem0HttpClient:
    def __init__(self, api_key: str, user_id: str | None = None, timeout: int = 30):
        self.api_key = api_key
        self.user_id = resolve_user_id(user_id)
        self.timeout = timeout
        self.base_url = "https://api.mem0.ai"

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mem0 HTTP {exc.code}: {body[:300]}") from exc

    def list_memories(self) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"user_id": self.user_id, "page_size": 200})
        result = self._request("GET", f"/v1/memories/?{query}")
        return result.get("results", result) if isinstance(result, dict) else result

    def search_memories(
        self,
        query: str,
        filters: dict[str, Any],
        top_k: int = 10,
        threshold: float = 0.1,
    ) -> list[dict[str, Any]]:
        result = self._request(
            "POST",
            "/v3/memories/search/",
            {
                "query": query,
                "filters": filters,
                "top_k": top_k,
                "threshold": threshold,
                "rerank": True,
            },
        )
        return result.get("results", result) if isinstance(result, dict) else result

    def update_memory(
        self,
        memory_id: str,
        text: str,
        metadata: dict[str, Any],
        expiration_date: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/memories/{memory_id}/",
            {"text": text, "metadata": metadata, "expiration_date": expiration_date},
        )

    def add_memory(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/v3/memories/add/",
            {
                "messages": [{"role": "user", "content": text}],
                "user_id": self.user_id,
                "metadata": metadata,
                "infer": False,
            },
        )
        candidates = result.get("results") or result.get("memories") or []
        if not candidates:
            raise RuntimeError("Mem0 ekleme yanıtında kayıt kimliği yok")
        first = candidates[0]
        if "memory" not in first and isinstance(first.get("data"), dict):
            first = {"id": first["id"], "memory": first["data"].get("memory", text), "metadata": metadata}
        return first

    def delete_memory(self, memory_id: str) -> Any:
        return self._request("DELETE", f"/v1/memories/{memory_id}/")


def mem0_config(vault: Path | None = None) -> dict:
    if vault is None:
        return {}
    path = Path(vault) / "komuta/mem0.json"
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError("Mem0 ayar yolu geçersiz")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"enabled", "user_id", "credentials_file"}:
        raise ValueError("Mem0 ayarı geçersiz")
    if type(config.get("enabled")) is not bool or not isinstance(config.get("user_id"), str) or not config["user_id"]:
        raise ValueError("Mem0 ayarı geçersiz")
    return config


def load_api_key(vault: Path | None = None) -> str:
    if os.environ.get("MEM0_API_KEY"):
        return os.environ["MEM0_API_KEY"]
    config = mem0_config(vault)
    if config.get("enabled"):
        path = Path(config.get("credentials_file", ""))
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("Mem0 anahtar dosyası geçersiz")
        if vault is not None and path.resolve().is_relative_to(Path(vault).resolve()):
            raise ValueError("Mem0 anahtarı kasa dışında olmalı")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Mem0 anahtar dosyası geçersiz")
        value = data.get("MEM0_API_KEY")
        if not isinstance(value, str) or not value or any(c.isspace() for c in value):
            raise ValueError("Mem0 anahtar dosyası geçersiz")
        return value
    config_path = Path.home() / ".claude.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return config["mcpServers"]["mem0"]["env"]["MEM0_API_KEY"]
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("MEM0_API_KEY bulunamadı") from exc


def write_receipt(vault: Path, operation: str, payload: dict[str, Any]) -> Path:
    directory = vault / "günlük" / "hafıza-makbuzları"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{timestamp}-{operation}-{uuid.uuid4().hex[:8]}.json"
    envelope = {
        "receipt_id": str(uuid.uuid4()),
        "operation": operation,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "payload": payload,
        "schema_version": 1,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Obsidian ↔ Mem0 hafıza kapısı")
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument(
        "--user-id",
        default=None,
        help="Mem0 kimliği; verilmezse HAFIZA_MEM0_USER_ID, o da yoksa varsayılan kullanılır.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate")
    sub.add_parser("audit")
    binding = sub.add_parser("bind-source")
    binding.add_argument("--input-json", type=Path, required=True)
    binding.add_argument("--apply", action="store_true")
    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("--apply", action="store_true")

    candidate = sub.add_parser("candidate-add")
    candidate.add_argument("--statement", required=True)
    candidate.add_argument("--kind", default="semantic", choices=sorted(VALID_KINDS))
    candidate.add_argument("--scope", required=True)
    candidate.add_argument("--subject-key", required=True)
    candidate.add_argument("--source-path", required=True)
    candidate.add_argument("--source-anchor", required=True)
    candidate.add_argument("--confidence", default="explicit-user")
    candidate.add_argument("--sensitivity", default="normal", choices=sorted(VALID_SENSITIVITIES))
    candidate.add_argument("--proposed-by", required=True)
    candidate.add_argument("--evidence", help="Kaynak dosyada aynen bulunan kısa kullanıcı beyanı")

    candidate.add_argument("--rationale")
    candidate.add_argument("--conditions")

    assess = sub.add_parser("candidate-assess")
    assess.add_argument("candidate_id")

    promote = sub.add_parser("promote")
    promote.add_argument("candidate_id")
    promote.add_argument("--memory-id", required=True)
    promote.add_argument("--reviewed-by", required=True)
    promote.add_argument("--supersedes")
    promote.add_argument("--apply", action="store_true")

    context = sub.add_parser("context")
    context.add_argument("query")
    context.add_argument("--local", action="store_true", help="Bu çağrıda Mem0 erişimini kapat")
    context.add_argument("--remote", action="store_true", help="İsteğe bağlı Mem0 sıralaması; hata halinde yerel erişim")
    context.add_argument("--scope", default="user")
    context.add_argument("--limit", type=int, default=5)
    context.add_argument("--char-budget", type=int, default=1200)
    context.add_argument("--threshold", type=float, default=0.1)

    evaluation = sub.add_parser("eval")
    evaluation.add_argument("--file", type=Path, default=Path("araclar/hafıza-testleri.json"))
    evaluation.add_argument("--threshold", type=float, default=0.1)
    evaluation.add_argument("--min-accuracy", type=float, default=0.9)

    forget = sub.add_parser("forget")
    forget.add_argument("memory_id")
    forget.add_argument("--approved-by", required=True)
    forget.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    vault = args.vault.expanduser().resolve()
    records = load_catalog(vault)

    if args.command == "bind-source":
        _json_print(bind_source(vault, json.loads(args.input_json.read_text()), args.apply))
        return 0

    if args.command == "validate":
        errors = validate_catalog(vault, records)
        _json_print({"catalog_errors": errors, "record_count": len(records)})
        return 1 if errors else 0

    if args.command == "candidate-add":
        result = add_candidate(
            vault,
            statement=args.statement,
            kind=args.kind,
            scope=args.scope,
            subject_key=args.subject_key,
            source_path=args.source_path,
            source_anchor=args.source_anchor,
            confidence=args.confidence,
            sensitivity=args.sensitivity,
            proposed_by=args.proposed_by,
            evidence=args.evidence, rationale=args.rationale, conditions=args.conditions,
        )
        _json_print(result)
        return 0

    if args.command == "candidate-assess":
        candidates = load_jsonl(vault / CANDIDATE_PATH)
        candidate = next((item for item in candidates if item.get("candidate_id") == args.candidate_id), None)
        if candidate is None:
            raise ValueError("aday bulunamadı")
        _json_print(assess_candidate(candidate, records))
        return 0

    if args.command == "promote":
        result = promote_candidate(
            vault,
            args.candidate_id,
            memory_id=args.memory_id,
            reviewed_by=args.reviewed_by,
            supersedes=args.supersedes,
            apply=args.apply,
        )
        _json_print(result)
        return 0

    if args.command == "context":
        from gorev_baglam import hydrate_remote, rank_records
        errors = validate_catalog(vault, records)
        valid = [row for row in records if retrievable(row, args.scope) and not context_record_errors(vault, row)]
        ranked = rank_records(valid, args.query)
        results = [{'memory':row['statement'], 'metadata':row} for row in ranked]
        mode = 'local'; fallback = None
        if not args.local and (args.remote or mem0_config(vault).get("enabled", False)):
            try:
                client = Mem0HttpClient(load_api_key(vault), user_id=resolve_user_id(args.user_id or mem0_config(vault).get("user_id")))
                remote = client.search_memories(args.query, filters={'user_id':client.user_id}, top_k=max(args.limit*3,args.limit), threshold=args.threshold)
                remote_results = hydrate_remote(vault, remote, args.scope)
                seen = {item['metadata']['memory_id'] for item in remote_results}
                results = remote_results + [item for item in results if item['metadata']['memory_id'] not in seen]
                mode = 'remote+local'
            except (Exception,) as exc:
                fallback = type(exc).__name__
        result = context_from_results(
            results,
            query=args.query,
            scope=args.scope,
            limit=args.limit,
            char_budget=args.char_budget,
            records=records,
        )
        result.update(mode=mode, fallback_reason=fallback, catalog_errors=errors)
        _json_print(result)
        return 1 if errors else 0

    client = Mem0HttpClient(load_api_key(vault), user_id=resolve_user_id(args.user_id or mem0_config(vault).get("user_id")))
    if args.command == "audit":
        result = audit(vault, records, client)
        result["receipt"] = str(write_receipt(vault, "audit", result).relative_to(vault))
        _json_print(result)
        return 1 if any(result[k] for k in ("catalog_errors", "missing_remote", "drifted", "orphan_remote_ids", "duplicate_remote_groups")) else 0

    if args.command == "sync":
        result = sync_existing(vault, records, client, apply=args.apply)
        result["receipt"] = str(write_receipt(vault, "sync", result).relative_to(vault))
        _json_print(result)
        expected = sum(1 for record in records if record.get("mem0_id") or (args.apply and record["status"] == "active"))
        return 0 if result["verified"] == expected and not result.get("reconciliation_required") else 1

    if args.command == "eval":
        path = args.file if args.file.is_absolute() else vault / args.file
        cases = json.loads(path.read_text(encoding="utf-8"))
        result = evaluate_retrieval(client, cases, user_id=client.user_id, threshold=args.threshold)
        result["minimum_accuracy"] = args.min_accuracy
        result["gate_passed"] = evaluation_passes(result, minimum_accuracy=args.min_accuracy)
        result["receipt"] = str(write_receipt(vault, "eval", result).relative_to(vault))
        _json_print(result)
        return 0 if result["gate_passed"] else 1

    if args.command == "forget":
        record = next((item for item in records if item.get("memory_id") == args.memory_id), None)
        if record is None:
            raise ValueError("memory_id bulunamadı")
        result = forget_remote(record, client, approved_by=args.approved_by, apply=args.apply)
        result["receipt"] = str(write_receipt(vault, "forget", result).relative_to(vault))
        _json_print(result)
        return 0

    raise AssertionError(f"bilinmeyen komut: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        _json_print({"error": str(exc)})
        raise SystemExit(2)
