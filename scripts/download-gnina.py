"""Install the checksum-pinned official x86_64 GNINA v1.3.3 binary (CUDA 12.8 static build, run CPU-only)."""
import hashlib
import platform
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

SHA256 = '3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172'
URL = 'https://github.com/gnina/gnina/releases/download/v1.3.3/gnina.cuda12.8.static'
if platform.machine() not in ('x86_64', 'AMD64'):
    raise SystemExit('This pinned binary requires x86_64 Linux.')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


target = Path(sys.argv[1] if len(sys.argv) > 1 else 'tools/gnina')
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    source = target
else:
    # The binary is about 2 GB, so stream it to a temporary file next to the target instead of holding it in memory.
    handle = tempfile.NamedTemporaryFile(dir=target.parent, prefix='.gnina-', delete=False)
    source = Path(handle.name)
    with handle, urllib.request.urlopen(URL, timeout=120) as response:
        shutil.copyfileobj(response, handle, 1 << 20)
if sha256_file(source) != SHA256:
    if source != target:
        source.unlink()
    raise SystemExit('GNINA checksum mismatch')
if source != target:
    source.replace(target)
target.chmod(0o755)
print('GNINA 1.3.3 checksum verified.')
