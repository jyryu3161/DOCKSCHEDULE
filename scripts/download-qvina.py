"""Install the checksum-pinned official x86_64 QuickVina 2.1 binary."""
import hashlib
import platform
import sys
import urllib.request
from pathlib import Path

SHA256 = 'bc1f908869181d17b48c9a9b4c2a28cce5264ccf3053e15bce32bb5baf83b43d'
URL = 'https://raw.githubusercontent.com/QVina/qvina/f4bb3b1073a0d50bb2f1fdd14d38594f937602ee/bin/qvina2.1'
if platform.machine() not in ('x86_64', 'AMD64'):
    raise SystemExit('This pinned binary requires x86_64 Linux.')
target = Path(sys.argv[1] if len(sys.argv)>1 else 'tools/qvina2.1')
data = target.read_bytes() if target.exists() else urllib.request.urlopen(URL, timeout=120).read()
if hashlib.sha256(data).hexdigest() != SHA256:
    raise SystemExit('QuickVina checksum mismatch')
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
target.chmod(0o755)
print('QuickVina 2.1 checksum verified.')
