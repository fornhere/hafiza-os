import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from kullanim_kontrol import check, observe, prepare_image

class Usage(unittest.TestCase):
    def test_prepare_returns_exact_object_after_validation(self):
        from unittest.mock import patch
        args={'prompt':'Create a cover','referenced_image_paths':['/fixture/identity.png']}
        with patch('kullanim_kontrol.validate_inputs',return_value=args['referenced_image_paths']) as validate:
            self.assertIs(prepare_image({'assets':['fixture']},args),args)
            validate.assert_called_once_with(['fixture'],args['referenced_image_paths'],role='identity')

    def test_prepare_invalid_or_wrong_assets_prevent_invocation(self):
        from unittest.mock import patch,Mock
        tool=Mock()
        cases=[{}, {'prompt':'cover'}, {'prompt':'cover','referenced_image_paths':[]},
               {'prompt':'cover','referenced_image_paths':['/wrong'],'num_last_images_to_include':1},
               {'prompt':'cover','referenced_image_paths':['/wrong']}]
        with patch('kullanim_kontrol.validate_inputs',side_effect=ValueError('wrong asset')):
            for args in cases:
                with self.assertRaises(ValueError): tool(prepare_image({'assets':[]},args))
        tool.assert_not_called()

    def test_real_shape_adapter_requires_direct_exact_call_and_never_infers_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); asset=root/'identity.png'; asset.write_bytes(b'identity')
            approval=root/'approval'; approval.write_text('Approved identity reference by user.')
            package={'assets':[{'role':'identity','path':str(asset),'allowed_roots':[d],
                'status':'approved','sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),
                'approval_source':str(approval),'approval_evidence':approval.read_text()}]}
            meta={'type':'session_meta','payload':{'id':'main','source':'cli'}}
            call={'type':'function_call','name':'imagegen','namespace':'image_gen','call_id':'c1',
                  'arguments':json.dumps({'referenced_image_paths':[str(asset)]})}
            output={'type':'function_call_output','call_id':'c1','output':'anything'}
            path=root/'rollout.jsonl'
            def write(c=call,o=output,m=meta):
                path.write_text('\n'.join(json.dumps(x) for x in [m,{'type':'response_item','payload':c},{'type':'response_item','payload':o}]))
            write(); result=observe(package,path,'c1','main')
            self.assertEqual(result['input_check'],'passed')
            self.assertEqual(result['technical_outcome'],'unknown')
            self.assertEqual(result['user_acceptance'],'unknown')
            self.assertEqual(result['tool_result'],'present_unclassified')
            write(o=dict(output,output=json.dumps({'isError':True})))
            self.assertEqual(observe(package,path,'c1','main')['tool_result'],'reported_error')
            for args in ({'num_last_images_to_include':1}, {'prompt':str(asset)},
                         {'referenced_image_paths':[str(asset)],'num_last_images_to_include':1}):
                write(c=dict(call,arguments=json.dumps(args)))
                self.assertEqual(observe(package,path,'c1','main')['input_check'],'unknown')
            write(c=dict(call,arguments=json.dumps({'referenced_image_paths':[str(root/'wrong.png')]})))
            self.assertEqual(observe(package,path,'c1','main')['input_check'],'failed')
            write(c={'type':'custom_tool_call','name':'exec','call_id':'c1',
                     'input':'await tools.image_gen__imagegen('+json.dumps({'referenced_image_paths':[str(asset)]})+')'})
            self.assertEqual(observe(package,path,'c1','main')['input_check'],'unknown')
            write(m={'type':'session_meta','payload':{'id':'child','source':{'subagent':'main'}}})
            with self.assertRaises(ValueError): observe(package,path,'c1','main')
            write(); path.write_text(path.read_text()+'\n'+json.dumps({'type':'response_item','payload':call}))
            with self.assertRaises(ValueError): observe(package,path,'c1','main')
            path.write_text('{broken')
            with self.assertRaises(ValueError): observe(package,path,'c1','main')

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
