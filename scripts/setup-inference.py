"""Install a bounded, verified CPU runtime/model inside ignored workspace paths."""
import hashlib
from pathlib import Path
import zipfile
import argparse
import sys
import json

import httpx

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'b11852'


def download(url, destination, checksum, max_bytes):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        with destination.open('rb') as existing:
            if hashlib.file_digest(existing, 'sha256').hexdigest() == checksum:
                print(f'Already verified: {destination.name}', flush=True)
                return
    temporary = destination.with_suffix(destination.suffix + '.part')
    for attempt in range(5):
        received = temporary.stat().st_size if temporary.exists() else 0
        digest = hashlib.sha256()
        if received:
            with temporary.open('rb') as prefix:
                for block in iter(lambda: prefix.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() == checksum:
                break
        reported = received
        try:
            with httpx.stream('GET', url, headers={'Range': f'bytes={received}-'} if received else {}, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                if received and response.status_code != 206:
                    received, digest = 0, hashlib.sha256()
                if response.status_code == 206 and not response.headers.get('content-range', '').startswith(f'bytes {received}-'):
                    raise RuntimeError('Unexpected resumed download range')
                with temporary.open('ab' if received else 'wb') as output:
                    for block in response.iter_bytes(1024 * 1024):
                        received += len(block)
                        if received > max_bytes:
                            raise RuntimeError('Download exceeded its expected size budget')
                        output.write(block)
                        digest.update(block)
                        if received - reported > 20_000_000:
                            reported = received
                            print(f'{destination.name}: {received // 1_000_000} MB', flush=True)
            if digest.hexdigest() != checksum:
                raise RuntimeError(f'Checksum mismatch for {destination.name}; partial file not activated')
            break
        except httpx.HTTPError:
            if attempt == 4:
                raise
            print(f'Download interrupted; retrying from {received // 1_000_000} MB', flush=True)
    temporary.replace(destination)
    print(f'Verified SHA-256: {destination.name}', flush=True)


def main():
    if sys.platform != 'win32':
        raise SystemExit('This bounded setup downloads Windows x64 binaries. Use an official llama.cpp build or Ollama on other platforms; see docs/inference-ocr.md.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-host', choices=('huggingface', 'modelscope'), default='modelscope')
    parser.add_argument('--model', choices=('qwen', 'gemma'), default='qwen')
    args = parser.parse_args()
    profile = json.loads((ROOT / 'scripts' / 'model-profiles.json').read_text(encoding='utf-8'))[args.model]
    repository, filename = profile['repository'], profile['filename']
    print(f'Selected {args.model}: {filename}; license: {profile["license"]}', flush=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        release = client.get(f'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{RELEASE}')
        release.raise_for_status()
        asset = next(a for a in release.json()['assets'] if a['name'] == f'llama-{RELEASE}-bin-win-cpu-x64.zip')
        if args.model_host == 'modelscope':
            model = client.get(f'https://modelscope.cn/api/v1/models/{repository}/repo/files?Revision={profile["revision"]}&Recursive=true')
            model.raise_for_status()
            item = next(f for f in model.json()['Data']['Files'] if f['Name'] == filename)
            model_url = f'https://modelscope.cn/models/{repository}/resolve/{profile["revision"]}/{filename}'
            checksum = item['Sha256']
        else:
            model = client.get(f'https://huggingface.co/api/models/{repository}/revision/{profile["revision"]}?blobs=true')
            model.raise_for_status()
            model = model.json()
            item = next(f for f in model['siblings'] if f['rfilename'] == filename)
            model_url = f'https://huggingface.co/{repository}/resolve/{profile["revision"]}/{filename}'
            checksum = item['lfs']['sha256']
    archive = ROOT / '.local' / asset['name']
    download(asset['browser_download_url'], archive, asset['digest'].removeprefix('sha256:'), 40_000_000)
    destination = (ROOT / '.local' / 'llama.cpp').resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise RuntimeError('Unsafe archive path')
        for member in package.infolist():
            target = destination / member.filename
            if not member.is_dir() and target.is_file() and target.stat().st_size == member.file_size:
                with package.open(member) as source, target.open('rb') as existing:
                    if hashlib.file_digest(source, 'sha256').digest() == hashlib.file_digest(existing, 'sha256').digest():
                        continue  # Preserve identical runtime files, including a running Qwen server.
            try:
                package.extract(member, destination)
            except PermissionError as exc:
                raise RuntimeError('Runtime update needs a writable file. Stop the local model server and retry; no model substitution was performed.') from exc
    if checksum != profile['sha256']:
        raise RuntimeError('Repository checksum differs from the pinned model profile; no model was activated')
    download(model_url, ROOT / '.models' / filename, profile['sha256'], profile['bytes'])
    print(f'CPU runtime and {args.model} installed. No application credentials changed.', flush=True)


if __name__ == '__main__':
    main()
