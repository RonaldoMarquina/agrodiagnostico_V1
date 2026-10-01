#!/usr/bin/env python3
"""Prepare persistent local Ed25519 keys without printing or replacing secrets."""
import argparse
import os
from pathlib import Path
import subprocess


def openssl(*args):
    result = subprocess.run(['openssl', *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError('configuration_invalid: Ed25519 key material')
    return result.stdout


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = directory / 'jwt_private_key.pem'
    public = directory / 'jwt_public_key.pem'
    if not private.exists():
        if public.exists():
            raise ValueError('configuration_invalid: public key exists without private key')
        data = openssl('genpkey', '-algorithm', 'ED25519')
        fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    derived = openssl('pkey', '-in', str(private), '-pubout')
    description = openssl('pkey', '-in', str(private), '-text_pub', '-noout')
    if b'ED25519' not in description:
        raise ValueError('configuration_invalid: Ed25519 required')
    if public.exists():
        if public.read_bytes().strip() != derived.strip():
            raise ValueError('configuration_invalid: public/private key mismatch')
    else:
        fd = os.open(public, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(derived)
    private.chmod(0o600)
    public.chmod(0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('.local/persistence'))
    args = parser.parse_args()
    try:
        prepare(args.directory)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, ValueError) else 'configuration_invalid: key files')
    print('Identity Ed25519 keys ready; no secret values printed.')
