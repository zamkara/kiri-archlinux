"""Check package metadata, integration files, and ELF runtime dependencies."""
import hashlib,json,pathlib,subprocess,sys

def validate(root):
    state=json.loads((root/'upstream.json').read_text())
    packages=list(root.glob('*.pkg.tar.zst'))
    if len(packages)!=1:raise SystemExit(f'Expected one package, found {len(packages)}')
    package=packages[0]
    subprocess.run(['pacman','-Qip',str(package)],check=True)
    listing=set(subprocess.check_output(['bsdtar','-tf',str(package)],text=True).splitlines())
    required=[
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
    ]
    for name in required:
        if name not in listing:raise SystemExit(f'Missing package member: {name}')
    for binary in (root/'.cache/target-engine/release/kiri',root/'.cache/target-window/release/kiri'):
        if binary.exists():
            result=subprocess.run(['ldd',str(binary)],capture_output=True,text=True)
            if result.returncode or 'not found' in result.stdout:
                raise SystemExit(f'Unresolved binary dependencies: {result.stdout}\n{result.stderr}')
    state['package']=package.name
    (root/'upstream.json').write_text(json.dumps(state,indent=2)+'\n')
    files=[package,root/'install.sh',root/'PKGBUILD',root/'.SRCINFO',root/'upstream.json']
    with (root/'SHA256SUMS').open('w') as stream:
        for path in files:
            digest=hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
            stream.write(f'{digest.hexdigest()}  {path.name}\n')
    print('Validated native Arch package:',package.name)

if __name__=='__main__':
    validate(pathlib.Path(sys.argv[1]))
