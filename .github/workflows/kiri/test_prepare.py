import json,pathlib,tempfile,unittest
from unittest.mock import patch
import prepare

SAMPLE_CLI_PINS = (
    'pub const LINUX_DOCKER_CLI: (&str, &str) = ("29.9.2", "' + 'a' * 64 + '");\n'
    'pub const LINUX_COMPOSE: (&str, &str) = ("v5.6.1", "' + 'b' * 64 + '");\n'
    'pub const LINUX_BUILDX: (&str, &str) = ("v0.38.1", "' + 'c' * 64 + '");\n'
)

class PlanningTests(unittest.TestCase):
    def test_identical_published_inputs_skip(self):
        state={'commit':'a'*40,'recipe_sha256':'c'*64}
        self.assertTrue(prepare.same_inputs(dict(state),state))
        self.assertFalse(prepare.same_inputs(None,state))
        for key in state:
            changed=dict(state);changed[key]='different'
            self.assertFalse(prepare.same_inputs(state,changed))

    def test_skip_happens_before_source_download_or_changelog_fetch(self):
        commit='a'*40;recipe='b'*64
        old={'app':'kiri','commit':commit,'recipe_sha256':recipe}
        def api(path):
            if path=='repos/libracoder/kiri':return {'default_branch':'main'}
            if path=='repos/libracoder/kiri/commits/main':return {'sha':commit,'commit':{'committer':{'date':'2026-11-15T13:19:10Z'}}}
            if path=='repos/libracoder/kiri/releases/latest':return {'tag_name':'v0.2.1'}
            raise AssertionError('Unexpected request: '+path)
        def content(repo,path,sha):
            return SAMPLE_CLI_PINS if path=='crates/kiri/src/cli_pins.rs' else ''
        with tempfile.TemporaryDirectory() as directory,patch('sys.argv',['prepare.py','--directory',directory]),patch.object(prepare,'api',api),patch.object(prepare,'content',content),patch.object(prepare,'recipe_hash',return_value=recipe),patch.object(prepare,'previous',return_value=old),patch.object(prepare,'download_archive') as archive,patch.object(prepare,'notes') as notes,patch.object(prepare,'output') as output:
            prepare.main();archive.assert_not_called();notes.assert_not_called()
            self.assertEqual(output.call_args.args[0]['changed'],'false')

    def test_changed_upstream_generates_pkgbuild_and_installer(self):
        commit='a'*40;recipe='b'*64
        def api(path):
            if path=='repos/libracoder/kiri':return {'default_branch':'main'}
            if path=='repos/libracoder/kiri/commits/main':return {'sha':commit,'commit':{'committer':{'date':'2026-11-15T13:19:10Z'}}}
            if path=='repos/libracoder/kiri/releases/latest':return {'tag_name':'v0.2.1'}
            raise AssertionError('Unexpected request: '+path)
        def content(repo,path,sha):
            return SAMPLE_CLI_PINS
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            with patch('sys.argv',['prepare.py','--directory',directory]),patch.object(prepare,'api',api),patch.object(prepare,'content',content),patch.object(prepare,'recipe_hash',return_value=recipe),patch.object(prepare,'previous',return_value=None),patch.object(prepare,'download_archive',return_value=('kiri.tar.gz::https://example.com','d'*64)),patch.object(prepare,'notes',return_value='Release notes\n'),patch.object(prepare,'output') as output:
                prepare.main()
                self.assertEqual(output.call_args.args[0]['changed'],'true')
                self.assertTrue((root/'PKGBUILD').is_file())
                self.assertTrue((root/'install.sh').is_file())
                self.assertIn('kiri-0.2.1.r20261115131910.gaaaaaaaaaaaa-1',(root/'install.sh').read_text())

    def test_snapshot_version_is_reproducible(self):
        self.assertEqual(prepare.pkgversion('v0.2.1','2026-11-15T13:19:10Z','a'*40),'0.2.1.r20261115131910.gaaaaaaaaaaaa')

    def test_changelog_preserves_upstream_commit_messages(self):
        message='Engine: restarts on the new version after every update (#48)'
        with patch.object(prepare,'api',return_value={'commits':[{'commit':{'message':message},'html_url':'https://github.com/libracoder/kiri/commit/abc'}]}):
            self.assertIn(message,prepare.changes('libracoder/kiri','abc','def'))

if __name__=='__main__':unittest.main()
