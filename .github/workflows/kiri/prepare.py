"""Pin upstream HEAD, skip already published inputs, and generate a PKGBUILD."""
import argparse,base64,hashlib,json,os,pathlib,re,shlex,time
import urllib.error,urllib.parse,urllib.request

HERE=pathlib.Path(__file__).resolve().parent
API='https://api.github.com/'
UPSTREAM='libracoder/kiri'
APP='kiri'
PIN_RE=re.compile(
    r'pub const LINUX_(DOCKER_CLI|COMPOSE|BUILDX): \(&str, &str\) = '
    r'\("([^"]+)", "([0-9a-f]{64})"\);'
)

def request(url,accept='application/vnd.github+json'):
    headers={'Accept':accept,'User-Agent':'kiri-archlinux-workflow'}
    if url.startswith(API) and os.environ.get('GH_TOKEN'):
        headers['Authorization']='Bearer '+os.environ['GH_TOKEN']
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429,500,502,503,504) or attempt==3:raise
        except (TimeoutError,urllib.error.URLError):
            if attempt==3:raise
        time.sleep(2**attempt)
    raise RuntimeError('Unreachable request')

def api(path):return json.loads(request(API+path))

def content(repo,path,sha):
    value=api(f'repos/{repo}/contents/{path}?ref={sha}')
    return base64.b64decode(value['content']).decode()

def releases(repo):
    page=1
    while True:
        values=api(f'repos/{repo}/releases?per_page=100&page={page}')
        yield from values
        if len(values)<100:break
        page+=1

def previous(repo):
    for release in releases(repo):
        if release['draft']:continue
        asset=next((x for x in release['assets'] if x['name']=='upstream.json'),None)
        if asset:
            state=json.loads(request(asset['url'],'application/octet-stream'))
            if state.get('app')!=APP:raise ValueError('Incorrect release state')
            if not any(x['name']==state.get('package') for x in release['assets']):
                raise ValueError('Incomplete published release')
            return state
    return None

def recipe_hash():
    h=hashlib.sha256()
    for name in ('PKGBUILD.in','install.sh.in','build.sh','validate.py','patch_updater.py'):
        h.update(name.encode());h.update((HERE/name).read_bytes())
    return h.hexdigest()

def same_inputs(old,new):
    return old is not None and all(old.get(k)==new.get(k) for k in ('commit','recipe_sha256'))

def pkgversion(version,stamp,sha):
    # Timestamp comes from the commit, not this workflow run, for deterministic rebuilds.
    base=re.sub(r'[^A-Za-z0-9.+_]','.',version.lstrip('v'))
    date=re.sub(r'[^0-9]','',stamp)[:14]
    return f'{base}.r{date}.g{sha[:12]}'

def parse_cli_pins(text):
    found={name:(ver,digest) for name,ver,digest in PIN_RE.findall(text)}
    if set(found)!={'DOCKER_CLI','COMPOSE','BUILDX'}:
        raise ValueError('Missing Linux CLI pins in crates/kiri/src/cli_pins.rs')
    return {
        'docker':{'version':found['DOCKER_CLI'][0],'sha256':found['DOCKER_CLI'][1]},
        'compose':{'version':found['COMPOSE'][0],'sha256':found['COMPOSE'][1]},
        'buildx':{'version':found['BUILDX'][0],'sha256':found['BUILDX'][1]},
    }

def upstream_version(repo,sha):
    try:
        rel=api(f'repos/{repo}/releases/latest')
        tag=str(rel.get('tag_name','')).lstrip('v')
        if tag and re.fullmatch(r'\d+\.\d+\.\d+',tag):
            return tag
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
    cargo=content(repo,'Cargo.toml',sha)
    match=re.search(r'^version\s*=\s*"([^"]+)"',cargo,re.M)
    ver=match.group(1) if match else '0.0.0'
    return ver if ver!='0.0.0' else '0.2.1'

def changes(repo,base,head):
    result=[];page=1
    while True:
        data=api(f'repos/{repo}/compare/{base}...{head}?per_page=100&page={page}')
        commits=data.get('commits',[])
        result.extend(f"- {x['commit']['message']}\n  {x['html_url']}" for x in commits)
        if len(commits)<100:break
        page+=1
    return '\n\n'.join(result)

def notes(repo,sha,old):
    if old:
        text=changes(repo,old['commit'],sha)
        return text or f'https://github.com/{repo}/commit/{sha}\n'
    try:release=api(f'repos/{repo}/releases/latest')
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
        release=None
    if release:
        text=release.get('body') or release['html_url']
        tag=release['tag_name']
        extra=changes(repo,tag,sha)
        return text+('\n\n'+extra if extra else '')+'\n'
    commits=api(f'repos/{repo}/commits?sha={sha}&per_page=100')
    return '\n\n'.join(f"- {x['commit']['message']}\n  {x['html_url']}" for x in reversed(commits))+'\n'

def download_archive(repo,sha,directory,name):
    url=f'https://codeload.github.com/{repo}/tar.gz/{sha}'
    path=directory/name
    data=request(url);path.write_bytes(data)
    return f'{name}::{url}',hashlib.sha256(data).hexdigest()

def output(values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            for key,value in values.items():stream.write(f'{key}={value}\n')
    print(json.dumps(values))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',default=os.environ.get('GITHUB_REPOSITORY','zamkara/kiri-archlinux'))
    parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    directory=pathlib.Path(args.directory);directory.mkdir(parents=True,exist_ok=True)
    info=api(f'repos/{UPSTREAM}')
    commit=api(f'repos/{UPSTREAM}/commits/{urllib.parse.quote(info["default_branch"],safe="")}')
    sha=commit['sha']
    version=upstream_version(UPSTREAM,sha)
    pins=parse_cli_pins(content(UPSTREAM,'crates/kiri/src/cli_pins.rs',sha))
    description='Tiny, fast container runtime with the Docker Engine API, CLI, and native GTK/WebKitGTK window'
    state={
        'app':APP,
        'upstream':UPSTREAM,
        'branch':info['default_branch'],
        'commit':sha,
        'version':version,
        'commit_date':commit['commit']['committer']['date'],
        'recipe_sha256':recipe_hash(),
        'architecture':'x86_64',
        'binary':APP,
        'app_id':'dev.kiri.Kiri',
    }
    old=previous(args.repository)
    if same_inputs(old,state):
        output({'changed':'false','app':APP});return
    pkgver=pkgversion(version,state['commit_date'],sha)
    pkgrel=old.get('pkgrel',1)+1 if old and old.get('pkgver')==pkgver else 1
    tag=f'{APP}-{pkgver}-{pkgrel}'
    state.update(pkgver=pkgver,pkgrel=pkgrel,previous_commit=old['commit'] if old else None)
    source,checksum=download_archive(UPSTREAM,sha,directory,f'{APP}-{sha}.tar.gz')
    docker_ver=pins['docker']['version']
    compose_ver=pins['compose']['version']
    buildx_ver=pins['buildx']['version']
    sources=' '.join([
        shlex.quote(source),
        shlex.quote(f'docker-{docker_ver}.tgz::https://download.docker.com/linux/static/stable/x86_64/docker-{docker_ver}.tgz'),
        shlex.quote(f'docker-compose-{compose_ver}::https://github.com/docker/compose/releases/download/{compose_ver}/docker-compose-linux-x86_64'),
        shlex.quote(f'docker-buildx-{buildx_ver}::https://github.com/docker/buildx/releases/download/{buildx_ver}/buildx-{buildx_ver}.linux-amd64'),
    ])
    checksums=' '.join([
        shlex.quote(checksum),
        shlex.quote(pins['docker']['sha256']),
        shlex.quote(pins['compose']['sha256']),
        shlex.quote(pins['buildx']['sha256']),
    ])
    replacements={
        'PKGVER':pkgver,
        'PKGREL':str(pkgrel),
        'DESCRIPTION':shlex.quote(description),
        'URL':shlex.quote('https://github.com/'+UPSTREAM),
        'SHA':sha,
        'UPSTREAM_VERSION':shlex.quote(version),
        'BUILD_DATE':state['commit_date'][:10],
        'REPOSITORY':shlex.quote(args.repository),
        'DOCKER_VER':shlex.quote(docker_ver),
        'COMPOSE_VER':shlex.quote(compose_ver),
        'BUILDX_VER':shlex.quote(buildx_ver),
        'SOURCES':sources,
        'CHECKSUMS':checksums,
        'RELEASE_TAG':tag,
    }
    recipe=(HERE/'PKGBUILD.in').read_text()
    installer=(HERE/'install.sh.in').read_text()
    for key,value in replacements.items():
        recipe=recipe.replace('@'+key+'@',value)
        installer=installer.replace('@'+key+'@',value)
    (directory/'PKGBUILD').write_text(recipe)
    (directory/'patch_updater.py').write_bytes((HERE/'patch_updater.py').read_bytes())
    install_path=directory/'install.sh'
    install_path.write_text(installer)
    install_path.chmod(0o755)
    (directory/'upstream.json').write_text(json.dumps(state,indent=2)+'\n')
    (directory/'CHANGELOG.md').write_text(notes(UPSTREAM,sha,old))
    output({'changed':'true','app':APP,'tag':tag,'pkgver':pkgver,'recipe':state['recipe_sha256']})

if __name__=='__main__':main()
