import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import hafiza as h
from cikti_kayit import checked_output, verified_outputs, file_digest, review_binding
from is_ve_ders import put


class Outputs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name).resolve();(self.v/'komuta').mkdir();(self.v/'zihin').mkdir()
        self.project=self.v/'project';self.project.mkdir()
        self.file=self.project/'demo.txt';self.file.write_text('CSV example output')
        self.review=self.v/'review.md';self.review.write_text('CSV demo çıktı dosyası içerik ve biçim kontrolünden geçti.')
        (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[dict(id='atlas',aliases=['Atlas'],roots=[str(self.project)])]}))
        self.output=dict(id='demo',label='CSV öğretici demo',path=str(self.file),sha256=file_digest(self.file),verified_at=dt.datetime.now(dt.timezone.utc).isoformat(),reviewer='test',verification_path='review.md',verification_sha256=file_digest(self.review),verification_evidence=self.review.read_text(),uses=['CSV','eğitim'])
        self.review.write_text(self.review.read_text()+'\noutput-review: '+json.dumps(review_binding(self.output))+'\n')
        self.output['verification_sha256']=file_digest(self.review)
    def task(self, status='done'):
        return put(self.v,'task',dict(id='export',title='CSV demo',status=status,next_step='CSV kontrolü',project_id='atlas',source_path='review.md',evidence=self.review.read_text(),actor='test',last_verified=dt.date.today().isoformat(),outputs=[self.output]))
    def test_completed_task_output_is_verified_and_reusable(self):
        self.task();items=verified_outputs(self.v,'atlas')['outputs'];self.assertEqual(len(items),1);self.assertEqual(items[0]['path'],str(self.file))
        from yeniden_kullanim import propose
        result=propose(self.v,'atlas','CSV eğitim örneği');self.assertEqual(len(result['candidates']),1);self.assertEqual(result['status'],'proposed')
        self.assertEqual(propose(self.v,'atlas','uydu haritası')['candidates'],[])
    def test_changed_output_review_or_task_source_is_excluded(self):
        self.task();self.file.write_text('changed');self.assertEqual(verified_outputs(self.v,'atlas')['outputs'],[])
        self.file.write_text('CSV example output');self.review.write_text(self.review.read_text()+' Sonradan değişti.')
        self.assertEqual(verified_outputs(self.v,'atlas')['outputs'],[])
    def test_outside_root_and_forged_hash_rejected_at_write(self):
        self.output['path']=str(self.review)
        with self.assertRaises(ValueError):self.task()
        self.output['path']=str(self.file);self.output['sha256']='0'*64
        with self.assertRaises(ValueError):self.task()
        self.assertFalse((self.v/'zihin/is-durumu.jsonl').exists())
    def test_missing_proof_future_date_and_duplicate_rejected(self):
        self.output['verification_evidence']='not actually in review evidence'
        with self.assertRaises(ValueError):self.task()
        self.output['verification_evidence']=self.review.read_text();self.output['verified_at']='2999-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):self.task()
    def test_old_review_cannot_validate_another_output(self):
        other=self.project/'unreviewed.txt';other.write_text('Different unchecked output')
        forged=dict(self.output,path=str(other),sha256=file_digest(other))
        with self.assertRaisesRegex(ValueError,'review_not_bound'):
            checked_output(self.v,'atlas',forged)

    def test_cancelled_task_and_other_project_do_not_leak_output(self):
        self.task('cancelled');self.assertEqual(verified_outputs(self.v,'atlas')['outputs'],[])
        self.assertEqual(verified_outputs(self.v,'other')['outputs'],[])
    def test_symlink_and_private_rejected(self):
        alias=self.project/'alias';alias.symlink_to(self.file);self.output['path']=str(alias)
        with self.assertRaises(ValueError):self.task()
        self.output['path']=str(self.file);self.output['sensitivity']='private'
        with self.assertRaises(ValueError):self.task()


if __name__=='__main__':unittest.main()
