"""Anahtarın yalnız bağlı olduğu host'a gittiğini sınar; ağ yok, sahte/yerel taşıyıcılar."""
import email.message
import http.server
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.response
from pathlib import Path
from unittest.mock import patch

import hafiza
import jev_client as j


def _fake_https(seen, redirect_to):
    class FakeHTTPS(urllib.request.BaseHandler):
        def https_open(self, req):
            seen.append((req.host, req.get_header('Authorization')))
            headers = email.message.Message()
            if req.host == hafiza.MEM0_HOST:
                headers['Location'] = redirect_to
                response = urllib.response.addinfourl(io.BytesIO(b''), headers, req.full_url, 302)
            else:
                response = urllib.response.addinfourl(io.BytesIO(b'{"results": []}'), headers, req.full_url, 200)
            response.msg = 'fake'
            return response
    return FakeHTTPS


class Mem0RedirectTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True); env.start(); self.addCleanup(env.stop)

    def test_cross_host_redirect_fails_and_authorization_never_leaves(self):
        seen = []
        with patch.object(hafiza.urllib.request, 'HTTPSHandler', _fake_https(seen, 'https://evil.example/steal')):
            client = hafiza.Mem0HttpClient('sentetik-anahtar', user_id='ben')
            with self.assertRaisesRegex(ValueError, 'redirect_rejected'):
                client.search_memories('q', filters={'user_id': 'ben'})
            self.assertEqual(seen, [(hafiza.MEM0_HOST, 'Token sentetik-anahtar')])
            # Kontrol: varsayılan urllib yönlendirmesi başlığı başka host'a taşırdı.
            seen.clear()
            request = urllib.request.Request('https://api.mem0.ai/x', headers={'Authorization': 'Token sentetik-anahtar'})
            urllib.request.build_opener().open(request).close()
            self.assertIn(('evil.example', 'Token sentetik-anahtar'), seen)

    def test_same_host_redirect_is_rejected_too(self):
        seen = []
        with patch.object(hafiza.urllib.request, 'HTTPSHandler', _fake_https(seen, 'https://api.mem0.ai/other')):
            with self.assertRaisesRegex(ValueError, 'redirect_rejected'):
                hafiza.Mem0HttpClient('k', user_id='ben').list_memories()
        self.assertEqual(len(seen), 1)

    def test_key_bound_to_official_https_origin(self):
        seen = []
        with patch.object(hafiza.urllib.request, 'HTTPSHandler', _fake_https(seen, 'https://evil.example/')):
            for base in ('https://evil.example', 'http://api.mem0.ai', 'https://api.mem0.ai:8443',
                         'https://user' + '@api.mem0.ai', 'https://api.mem0.ai.evil.example'):
                with self.subTest(base=base):
                    client = hafiza.Mem0HttpClient('k', user_id='ben'); client.base_url = base
                    with self.assertRaisesRegex(ValueError, 'endpoint_invalid'):
                        client.list_memories()
        self.assertEqual(seen, [])


class JevEndpointBindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / 'kasa'; (self.vault / 'komuta').mkdir(parents=True)
        self.outside = Path(tmp.name) / 'disari'; self.outside.mkdir()
        self.cards = [dict(id='one', title='A', statement='B', scope='user', domains=['all'])]
        env = patch.dict(os.environ, {}, clear=True); env.start(); self.addCleanup(env.stop)
        self.calls = []

    def transport(self, url, body, key, timeout):
        self.calls.append((url, key))
        return dict(answers={q: dict(type='score', score=1.8) for q in body['questions']})

    def config(self, **kw):
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(mode='shadow', **kw)))

    def test_endpoint_policy_matrix(self):
        allowed = [('https://api.typesafe.ai', 'typesafe', False),
                   ('https://api.typesafe.ai:443/v1', 'typesafe', False),
                   ('https://ai-gateway.vercel.sh/typesafe', 'vercel', False),
                   ('http://127.0.0.1:18760', 'vercel', False),
                   ('http://localhost:18760', 'typesafe', False),
                   ('http://[::1]:18760/', 'vercel', False),
                   ('https://127.0.0.1:9', 'bilinmeyen', False),
                   ('https://jev.example', 'typesafe', True)]
        for base, provider, custom in allowed:
            with self.subTest(base=base, provider=provider):
                self.assertTrue(j._endpoint(base, provider, custom).endswith('/v1/systemone'))
        rejected = [('https://evil.example', 'typesafe', False),
                    ('https://api.typesafe.ai', 'vercel', False),
                    ('https://ai-gateway.vercel.sh', 'typesafe', False),
                    ('https://api.typesafe.ai.evil.example', 'typesafe', False),
                    ('https://api.typesafe.ai:8443', 'typesafe', False),
                    ('http://api.typesafe.ai', 'typesafe', False),
                    ('http://jev.example', 'typesafe', True),
                    ('https://u:p' + '@api.typesafe.ai', 'typesafe', False),
                    ('https://api.typesafe.ai?x=1', 'typesafe', False),
                    ('https://api.typesafe.ai#f', 'typesafe', False),
                    ('https://api.typesafe.ai\\@evil.example', 'typesafe', False),
                    ('https://api.typesafe.ai\n.evil.example', 'typesafe', False),
                    ('http://127.0.0.1:99999', 'vercel', False),
                    ('ftp://127.0.0.1', 'vercel', False),
                    ('https://evil.example', 'bilinmeyen', False),
                    (None, 'typesafe', False)]
        for base, provider, custom in rejected:
            with self.subTest(base=base, provider=provider):
                with self.assertRaisesRegex(ValueError, 'endpoint_invalid'):
                    j._endpoint(base, provider, custom)

    def test_environment_or_env_file_base_url_cannot_redirect_key(self):
        os.environ.update(TYPESAFE_API_KEY='env-key', TYPESAFE_BASE_URL='https://evil.example')
        self.config(provider='typesafe')
        result = j.evaluate(self.vault, 'q', self.cards, transport=self.transport)
        self.assertTrue(result['degraded']); self.assertIn('endpoint_invalid', json.dumps(result)); self.assertEqual(self.calls, [])
        del os.environ['TYPESAFE_BASE_URL']
        env_file = self.outside / 'jev.env'
        env_file.write_text('TYPESAFE_API_KEY=file-key\nTYPESAFE_BASE_URL=https://evil.example\n')
        self.config(provider='vercel', base_url='https://ai-gateway.vercel.sh/typesafe', env_file=str(env_file))
        self.assertTrue(j.evaluate(self.vault, 'q', self.cards, transport=self.transport)['degraded'])
        self.assertEqual(self.calls, [])

    def test_user_local_gateway_setup_keeps_working(self):
        # Kullanıcının gerçek kurulumunun biçimi: vercel + loopback base_url + env_file.
        env_file = self.outside / 'gateway.env'
        env_file.write_text('TYPESAFE_API_KEY=gateway-key\nTYPESAFE_BASE_URL=http://127.0.0.1:18760\n')
        self.config(provider='vercel', base_url='http://127.0.0.1:18760', env_file=str(env_file),
                    retrieval_mode='assist', model='typesafe-ai/jev')
        result = j.evaluate(self.vault, 'q', self.cards, transport=self.transport)
        self.assertFalse(result['degraded'])
        self.assertEqual(self.calls, [('http://127.0.0.1:18760/v1/systemone', 'gateway-key')])

    def test_allow_custom_endpoint_must_be_explicit_boolean(self):
        self.config(allow_custom_endpoint='true')
        with self.assertRaisesRegex(ValueError, 'config_invalid'):
            j._read_config(self.vault)
        os.environ['TYPESAFE_API_KEY'] = 'k'
        self.config(base_url='https://jev.example', allow_custom_endpoint=True)
        self.assertFalse(j.evaluate(self.vault, 'q', self.cards, transport=self.transport)['degraded'])
        self.assertEqual(self.calls, [('https://jev.example/v1/systemone', 'k')])


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.seen.append((self.path, self.headers.get('Authorization')))
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.server.redirect:
            self.send_response(302); self.send_header('Location', 'http://evil.example/steal'); self.end_headers()
            return
        body = b'{"answers": {}}'
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class JevLoopbackTransportTests(unittest.TestCase):
    def serve(self, redirect=False):
        server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
        server.seen, server.redirect = [], redirect
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(thread.join); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return server, 'http://127.0.0.1:%d/v1/systemone' % server.server_port

    def test_local_gateway_bypasses_environment_proxy(self):
        server, url = self.serve()
        with patch.dict(os.environ, {'http_proxy': 'http://proxy.invalid:9', 'HTTP_PROXY': 'http://proxy.invalid:9',
                                     'no_proxy': '', 'NO_PROXY': ''}):
            self.assertEqual(j._transport(url, {'x': 1}, 'local-key', 5), {'answers': {}})
        self.assertEqual(server.seen, [('/v1/systemone', 'Bearer local-key')])

    def test_local_gateway_redirect_rejected(self):
        server, url = self.serve(redirect=True)
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'redirect_rejected'):
            j._transport(url, {'x': 1}, 'local-key', 5)
        self.assertEqual(len(server.seen), 1)


if __name__ == '__main__':
    unittest.main()
