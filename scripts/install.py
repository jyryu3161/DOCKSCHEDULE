#!/usr/bin/env python3
"""Initialize secrets without printing them, then build and start Docker Compose."""
import getpass
import os
from pathlib import Path
import secrets
import subprocess

os.chdir(Path(__file__).resolve().parent.parent)
env = Path('.env')
if not env.exists():
    password = os.environ.get('ADMIN_PASSWORD') or getpass.getpass('Initial admin password: ')
    if len(password) < 8 or any(c in password for c in '\n\r\''):
        raise SystemExit('Use at least 8 characters, without newlines or single quotes.')
    env.write_text(f"ADMIN_PASSWORD='{password}'\nPOSTGRES_PASSWORD={secrets.token_hex(24)}\nBIND_IP=127.0.0.1\nAPP_PORT=8890\nALLOWED_NETWORKS=127.0.0.0/8,::1/128\nCOOKIE_SECURE=false\n")
    env.chmod(0o600)
subprocess.run(['docker','compose','up','--build','-d'],check=True)
