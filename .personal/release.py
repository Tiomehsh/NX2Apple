"""Follow official releases and publish the tested LCSign save-sync frontend.

The checked-out upstream repository and the bundled game tools stay unmodified.
Only an isolated frontend and a verified official release bundle are patched.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / '.personal-build'
UPSTREAM = 'LNPANDY/NX2Apple'
FORK = os.environ.get('GITHUB_REPOSITORY', 'Tiomehsh/NX2Apple')
REVISION = 1
ASSET = 'NX2Apple-macOS-arm64.zip'


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def api(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True))


def output(key, value):
    print(f'{key}={value}', flush=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'{key}={value}\n')


def personal_version(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError(f'Unsupported official release tag: {tag}')
    return f'{tag[1:]}.{REVISION}'


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f'Expected exactly one update anchor in {path.name}: {old}')
    path.write_text(text.replace(old, new))


def prepare():
    if FORK != 'Tiomehsh/NX2Apple':
        raise ValueError('This workflow only publishes to Tiomehsh/NX2Apple')
    official = api(f'repos/{UPSTREAM}/releases/latest')
    tag = official['tag_name']
    version = personal_version(tag)
    existing = api(f'repos/{FORK}/releases?per_page=100')
    if any(r['tag_name'] == 'v' + version and not r['draft'] and
           any(a['name'] == ASSET for a in r['assets']) for r in existing):
        output('build', 'no')
        return
    asset = next(a for a in official['assets'] if a['name'] == ASSET)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
        raise ValueError('Official release has no SHA-256 digest; refusing to package it')
    WORK.mkdir(exist_ok=True)
    source = WORK / 'frontend'
    if source.exists():
        shutil.rmtree(source)
    source.mkdir()
    run(['git', 'fetch', '--depth=1', '--no-tags',
         f'https://github.com/{UPSTREAM}.git', f'refs/tags/{tag}'], cwd=ROOT)
    commit = subprocess.check_output(['git', 'rev-parse', 'FETCH_HEAD^{commit}'], cwd=ROOT, text=True).strip()
    archive = WORK / 'frontend.tar'
    run(['git', 'archive', '--format=tar', '-o', archive, commit, 'frontend'], cwd=ROOT)
    run(['tar', '-xf', archive, '-C', source, '--strip-components=1'])
    patch = ROOT / '.personal/save-sync.patch'
    # No guessed context or forced conflict resolution. A changed upstream contract blocks publication.
    run(['git', 'apply', '-p2', '--check', patch], cwd=source)
    run(['git', 'apply', '-p2', patch], cwd=source)
    content = source / 'Sources/NSPortBuilder/ContentView.swift'
    replace_once(content, f'static let appVersion = "{tag[1:]}"',
                 f'static let appVersion = "{version}"')
    replace_once(content, f'https://api.github.com/repos/{UPSTREAM}/releases/latest',
                 f'https://api.github.com/repos/{FORK}/releases/latest')
    # BuildModel.repoURL intentionally remains official: game-engine/tool updates are independent.
    replace_once(source / 'Sources/NSPortBuilder/UpdateSheet.swift',
                 f'https://github.com/{UPSTREAM}/releases/tag/',
                 f'https://github.com/{FORK}/releases/tag/')
    state = {'official': official, 'asset': asset, 'version': version,
             'upstream_commit': commit, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest()}
    (WORK / 'state.json').write_text(json.dumps(state, indent=2))
    output('build', 'yes')
    output('version', version)


def package():
    state = json.loads((WORK / 'state.json').read_text())
    downloads = WORK / 'download'
    downloads.mkdir(exist_ok=True)
    run(['gh', 'release', 'download', state['official']['tag_name'], '-R', UPSTREAM,
         '--pattern', ASSET, '--dir', downloads, '--clobber'])
    archive = downloads / ASSET
    digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    if 'sha256:' + digest != state['asset']['digest']:
        raise ValueError('Official asset digest mismatch')
    bundle_dir = WORK / 'bundle'
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir()
    run(['ditto', '-x', '-k', archive, bundle_dir])
    app = bundle_dir / 'NX2Apple.app'
    info_path = app / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    if info['CFBundleIdentifier'] != 'org.nxnative.NSPortBuilder' or info['CFBundleShortVersionString'] != state['official']['tag_name'][1:]:
        raise ValueError('Unexpected official application identity/version')
    binary = WORK / 'frontend/.build/release/NSPortBuilder'
    architecture = subprocess.check_output(['lipo', '-archs', binary], text=True).strip()
    if 'arm64' not in architecture.split():
        raise ValueError(f'Expected an arm64 frontend, got {architecture}')
    shutil.copy2(binary, app / 'Contents/MacOS/NSPortBuilder')
    info['CFBundleShortVersionString'] = info['CFBundleVersion'] = state['version']
    info['NX2ApplePersonalPatch'] = 'lcsign-save-sync-1'
    info['NX2AppleUpstreamCommit'] = state['upstream_commit']
    info_path.write_bytes(plistlib.dumps(info))
    run(['codesign', '--force', '--sign', '-', app])
    run(['codesign', '--verify', '--deep', '--strict', app])
    run(['bash', ROOT / 'frontend/tools/check_bundle.sh', app])
    packed = WORK / ASSET
    if packed.exists():
        packed.unlink()
    run(['ditto', '-c', '-k', '--keepParent', app, packed])
    with packed.open('rb') as f:
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    (WORK / 'SHA256SUMS').write_text(f'{sha}  {ASSET}\n')
    proof = {k: state[k] for k in ('version', 'upstream_commit', 'patch_sha256')}
    proof['official_release'] = state['official']['html_url']
    proof['asset_sha256'] = sha
    (WORK / 'build-provenance.json').write_text(json.dumps(proof, indent=2))


def publish():
    state = json.loads((WORK / 'state.json').read_text())
    tag = 'v' + state['version']
    notes = WORK / 'release-notes.md'
    notes.write_text(
        f"Based on [{state['official']['tag_name']}]({state['official']['html_url']}).\n\n"
        'Personal LCSign save synchronization fix: detect connected installed containers without '
        'an Xcode installation receipt; support Documents/save and the per-game layout; parse '
        'current CoreDevice file metadata; use the Mac library save directory.\n\n'
        'Game tools continue to follow the official repository. No game files, keys, signing '
        'credentials or user saves are included. The personal updater follows this fork.\n\n'
        'Validation: SaveTransferTests and AppUpdateTests, release build, bundled-tool check '
        'and strict code-signature verification.\n\n---\n\n' + (state['official'].get('body') or ''))
    # A draft is only made public after every artifact is uploaded successfully.
    releases = api(f'repos/{FORK}/releases?per_page=100')
    draft = next((r for r in releases if r['tag_name'] == tag), None)
    if draft and not draft['draft']:
        raise ValueError('Refusing to replace an existing public release')
    if not draft:
        run(['gh', 'release', 'create', tag, '-R', FORK, '--draft', '--target',
             os.environ.get('GITHUB_SHA', 'personal/lcsign-sync'), '--title',
             f"NX2Apple {state['version']} · LCSign save sync", '--notes-file', notes])
    run(['gh', 'release', 'upload', tag, '-R', FORK, WORK / ASSET,
         WORK / 'SHA256SUMS', WORK / 'build-provenance.json', '--clobber'])
    run(['gh', 'release', 'edit', tag, '-R', FORK, '--draft=false', '--latest', '--notes-file', notes])
    print(f'https://github.com/{FORK}/releases/tag/{tag}')


if __name__ == '__main__':
    {'prepare': prepare, 'package': package, 'publish': publish}[sys.argv[1]]()
