"""Synthetic Claude/Codex skill parity tests; no real skill folders or sessions."""
import json
import os
from pathlib import Path
import tempfile
import unittest

import skill_esitlik as parity


class SkillParity(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.claude = self.root / 'claude'
        self.agents = self.root / 'agents'
        self.plugin = self.root / 'plugin'
        self.sessions = self.root / 'sessions'
        for folder in (self.claude, self.agents, self.plugin):
            folder.mkdir()

    def skill(self, root, name, body='Aynı yönerge.'):
        folder = root / name
        folder.mkdir()
        (folder / 'SKILL.md').write_text(f'---\nname: {name}\n---\n{body}\n', encoding='utf-8')
        return folder

    def link(self, target, link):
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('platform cannot create directory symlinks')

    def session(self, entries, name='rollout-1.jsonl', prefix_lines=1, private='Özel kullanıcı metni'):
        folder = self.sessions / '2026/09/28'
        folder.mkdir(parents=True, exist_ok=True)
        roots = {'r0': self.agents, 'r1': self.plugin}
        text = ('## Skills\n### Skill roots\n'
                + ''.join(f'- `{ref}` = `{path}`\n' for ref, path in roots.items())
                + '### Available skills\n'
                + ''.join(f'- {skill}: Açıklama: iki nokta içerir. (file: {ref}/{rel}/SKILL.md)\n'
                          for skill, ref, rel in entries))
        rows = [dict(type='event_msg', payload=dict(message=private))] * prefix_lines
        rows.append(dict(type='response_item', payload=dict(role='developer', content=[dict(text=text)])))
        rows.append(dict(type='response_item', payload=dict(role='user', content=[dict(text=private)])))
        path = folder / name
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        return path

    def run_check(self, patterns=()):
        return parity.check(self.claude, [self.agents], self.sessions, patterns=patterns)

    def codes(self, result):
        return {(i['code'], i['skill']) for i in result['issues']}

    def test_identical_link_is_healthy(self):
        self.link(self.skill(self.claude, 'video'), self.agents / 'video')
        self.session([('video', 'r0', 'video')])
        result = self.run_check()
        self.assertEqual('healthy', result['status'])
        self.assertEqual([], result['issues'])
        [(_, entries)] = parity.session_skills(self.sessions)
        self.assertEqual([('video', self.agents / 'video/SKILL.md')], entries)

    def test_missing_drift_and_copy_are_reported(self):
        self.skill(self.claude, 'eksik')
        self.skill(self.claude, 'kayan', 'Yeni sürüm.')
        self.skill(self.agents, 'kayan', 'Eski sürüm.')
        self.skill(self.claude, 'kopya')
        self.skill(self.agents, 'kopya')
        (self.claude / 'SKILL-olmayan').mkdir()
        result = self.run_check()
        self.assertEqual('problem', result['status'])
        self.assertEqual({('missing_in_codex', 'eksik'), ('content_drift', 'kayan'),
                          ('copy_not_link', 'kopya'), ('codex_session_unavailable', None)},
                         self.codes(result))

    def test_stale_plugin_version_loaded_with_current_skill_is_problem(self):
        self.link(self.skill(self.claude, 'hyperframes'), self.agents / 'hyperframes')
        self.skill(self.plugin, 'hyperframes', 'Eski eklenti sürümü.')
        self.session([('hyperframes', 'r0', 'hyperframes'),
                      ('hyperframes:hyperframes', 'r1', 'hyperframes')])
        result = self.run_check()
        self.assertEqual('problem', result['status'])
        issue = next(i for i in result['issues'] if i['code'] == 'conflicting_versions_loaded')
        self.assertEqual(['hyperframes', 'hyperframes:hyperframes'], issue['names'])
        self.assertEqual(1, issue['sessions'])

    def test_same_content_loaded_twice_is_warning_and_counts_sessions(self):
        self.link(self.skill(self.claude, 'core'), self.agents / 'core')
        self.skill(self.plugin, 'core')
        for index in range(3):
            self.session([('core', 'r0', 'core'), ('core', 'r1', 'core')], name=f'rollout-{index}.jsonl')
        result = self.run_check()
        self.assertEqual('warning', result['status'])
        self.assertEqual(3, result['codex_sessions'])
        issue = next(i for i in result['issues'] if i['code'] == 'duplicate_loaded')
        self.assertEqual(3, issue['sessions'])
        limited = parity.check(self.claude, [self.agents], self.sessions, limit=2)
        self.assertEqual(2, next(i for i in limited['issues'] if i['code'] == 'duplicate_loaded')['sessions'])

    def test_patterns_limit_scope(self):
        self.skill(self.claude, 'hyperframes-cli')
        self.skill(self.claude, 'yalniz-claude')
        self.skill(self.agents, 'hyperframes-cli')
        self.session([])
        result = self.run_check(patterns=['hyperframes*'])
        self.assertEqual(1, result['claude_skills'])
        self.assertNotIn(('missing_in_codex', 'yalniz-claude'), self.codes(result))

    def test_session_text_never_leaves_and_late_skills_block_is_ignored(self):
        self.link(self.skill(self.claude, 'video'), self.agents / 'video')
        self.session([('video', 'r0', 'video'), ('video', 'r0', 'video')], private='GİZLİ-İSTEM')
        result = self.run_check()
        self.assertNotIn('GİZLİ-İSTEM', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('GİZLİ-İSTEM', parity.render(result))
        late = self.session([], name='late.jsonl', prefix_lines=parity.MAX_HEADER_LINES)
        self.assertEqual([], parity.session_skills(session=late))

    def test_cli_exit_code_and_json(self):
        self.skill(self.claude, 'eksik')
        self.session([])
        args = ['--claude-root', str(self.claude), '--codex-root', str(self.agents),
                '--codex-sessions', str(self.sessions), '--json']
        from contextlib import redirect_stdout
        import io
        out = io.StringIO()
        with redirect_stdout(out):
            code = parity.main(args)
        self.assertEqual(1, code)
        self.assertEqual('problem', json.loads(out.getvalue())['status'])


if __name__ == '__main__':
    unittest.main()
