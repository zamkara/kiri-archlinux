import json,pathlib,tempfile,unittest
from unittest.mock import patch
import validate

class ValidateTests(unittest.TestCase):
    def test_validate_writes_package_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            pkg=root/'kiri-0.2.1-1-x86_64.pkg.tar.zst'
            pkg.write_bytes(b'pkg-bytes')
            for name in ('install.sh','PKGBUILD','.SRCINFO'):
                (root/name).write_bytes(name.encode())
            (root/'upstream.json').write_text(json.dumps({'app':'kiri'}))
            members='\n'.join([
                '.PKGINFO',
                '.BUILDINFO',
                'usr/bin/kiri',
                'usr/bin/kiri-init',
                'usr/lib/kiri/kiri-window',
                'usr/lib/kiri/arch-release.json',
                'usr/lib/kiri/docker-links.sh',
                'usr/lib/systemd/system/kiri.service',
                'usr/lib/sysusers.d/kiri.conf',
                'usr/libexec/kiri/bin/docker',
                'usr/libexec/kiri/docker',
                'usr/libexec/kiri/cli-plugins/docker-compose',
                'usr/libexec/kiri/cli-plugins/docker-buildx',
                'usr/share/applications/kiri.desktop',
                'usr/share/icons/hicolor/256x256/apps/kiri.png',
                'usr/share/icons/hicolor/scalable/apps/kiri.svg',
                'usr/share/libalpm/hooks/95-kiri-docker-links.hook',
                'usr/share/licenses/kiri/LICENSE',
                'usr/share/licenses/kiri/NOTICE',
                'usr/share/metainfo/dev.kiri.Kiri.metainfo.xml',
                'usr/share/polkit-1/actions/dev.kiri.host-access.policy',
            ])
            with patch('subprocess.run'),patch('subprocess.check_output',return_value=members):
                validate.validate(root)
            state=json.loads((root/'upstream.json').read_text())
            self.assertEqual(state['package'],pkg.name)
            sums=(root/'SHA256SUMS').read_text()
            self.assertIn(pkg.name,sums)
            self.assertIn('install.sh',sums)

if __name__=='__main__':unittest.main()
