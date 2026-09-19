import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hafiza
import kayit_uzlastir as subject

class LegacyRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        (self.v / "source.md").write_text("# Old source\nTurkish descriptive names preferred.")
        statement = "User prefers Turkish descriptive names and never uses numbered files."
        self.row = dict(memory_id="test", kind="semantic", scope="user", subject_key="files.names",
            statement=statement, status="active", source_path="source.md", source_anchor="Old source",
            source_hash=hafiza.statement_hash(statement), observed_at="2020-01-01", valid_from="2020-01-01",
            valid_to=None, confidence="explicit-user", sensitivity="normal", mem0_id="remote-id",
            supersedes=None, reviewed_by="old-reviewer", schema_version=1)
        hafiza._write_jsonl(self.v / hafiza.CATALOG_PATH, [self.row])
        self.data = dict(memory_id="test", action="narrow", expected_statement=statement,
            expected_catalog_hash=hafiza.statement_hash((self.v/hafiza.CATALOG_PATH).read_text()),
            expected_source_hash=hafiza.statement_hash((self.v/"source.md").read_text()),
            reviewed_by="codex-consolidator", semantic_reviewed=True,
            reason="Original summary supports names only; unsupported prohibition removed.",
            evidence="Turkish descriptive names preferred.", source_anchor="Old source",
            statement="User prefers Turkish descriptive names.")
    def test_dry_run_and_apply_preserve_history_and_readback(self):
        plan=subject.reconcile(self.v,self.data)
        self.assertEqual(hafiza.load_catalog(self.v),[self.row])
        self.assertFalse((self.v/subject.AUDIT).exists())
        result=subject.reconcile(self.v,self.data,True)
        new=hafiza.load_catalog(self.v)[0]
        for key in ("observed_at","valid_from","scope","kind","subject_key","mem0_id"):
            self.assertEqual(new[key],self.row[key])
        self.assertEqual(hafiza.context_record_errors(self.v,new),[])
        audit=hafiza.load_jsonl(self.v/subject.AUDIT)
        self.assertEqual([a['phase'] for a in audit],["prepared","applied"])
        self.assertEqual(audit[1]['before'],self.row)
        self.assertTrue(result['mem0_sync_required'])
        with self.assertRaisesRegex(ValueError,"catalog revision"):
            subject.reconcile(self.v,self.data,True)
    def test_changed_source_refused(self):
        (self.v/"source.md").write_text("Changed source")
        with self.assertRaisesRegex(ValueError,"source revision"):
            subject.reconcile(self.v,self.data,True)
    def test_reviewer_and_evidence_required(self):
        for key,value in (("reviewed_by","main-agent"),("semantic_reviewed",False),("evidence","Unsupported quote"),("source_anchor","Missing anchor")):
            data=dict(self.data,**{key:value})
            with self.assertRaises(ValueError):subject.reconcile(self.v,data,True)
        self.assertEqual(hafiza.load_catalog(self.v),[self.row])
    def test_nonlegacy_refused(self):
        row=dict(self.row,source_content_hash=self.data['expected_source_hash'])
        hafiza._write_jsonl(self.v/hafiza.CATALOG_PATH,[row])
        self.data['expected_catalog_hash']=hafiza.statement_hash((self.v/hafiza.CATALOG_PATH).read_text())
        with self.assertRaisesRegex(ValueError,"blocked legacy"):
            subject.reconcile(self.v,self.data,True)
    def test_quarantine_retains_statement(self):
        data=dict(self.data,action="quarantine");data.pop('statement')
        subject.reconcile(self.v,data,True)
        new=hafiza.load_catalog(self.v)[0]
        self.assertEqual(new['status'],'quarantined')
        self.assertEqual(new['statement'],self.row['statement'])
    def test_write_failure_never_records_applied(self):
        with patch.object(hafiza,'_write_jsonl',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):subject.reconcile(self.v,self.data,True)
        self.assertEqual([r['phase'] for r in hafiza.load_jsonl(self.v/subject.AUDIT)],["prepared"])
        self.assertEqual(hafiza.load_catalog(self.v),[self.row])
    def test_secret_refused(self):
        data=dict(self.data,statement="token: secret-value")
        with self.assertRaises(ValueError):subject.reconcile(self.v,data,True)

if __name__ == '__main__':unittest.main()
