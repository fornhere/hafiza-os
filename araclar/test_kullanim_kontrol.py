import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from kullanim_kontrol import check

class Usage(unittest.TestCase):
    def test_found_asset_is_not_execution_or_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); asset=root/'asset.png'; asset.write_bytes(b'fixture')
            source=root/'approval.md'; source.write_text('User approved this identity reference.')
            package={'project_id':'sample','assets':[{'id':'mascot','role':'identity','path':str(asset),
                'allowed_roots':[d],'status':'approved','sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),
                'approval_source':str(source),'approval_evidence':source.read_text()}]}
            invocation={'tool':'image','call_id':'one','actual_paths':[]}
            with self.assertRaises(ValueError): check(package,invocation)
            invocation['actual_paths']=[str(asset)]
            result=check(package,invocation)
            self.assertEqual(result['execution_evidence'],'preflight_only')
            self.assertEqual(result['user_declaration'],'unknown')
            trace=root/'trace.jsonl'; trace.write_text(json.dumps(invocation))
            invocation['trace']={'path':str(trace),'sha256':hashlib.sha256(trace.read_bytes()).hexdigest(),'evidence':trace.read_text()}
            self.assertEqual(check(package,invocation)['execution_evidence'],'trace_matched')
            trace.write_text('changed')
            with self.assertRaises(ValueError): check(package,invocation)
