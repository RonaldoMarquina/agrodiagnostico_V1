#!/usr/bin/env python3
"""Prepare persistent local Ed25519 internal worker keys and service trust registry."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def openssl(*args):
    result = subprocess.run(['openssl', *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError('configuration_invalid: Ed25519 internal key material')
    return result.stdout


def prepare(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    workers = [('worker-1', 'worker-1-key'), ('worker-2', 'worker-2-key')]
    trust_registry = {}

    for instance_id, kid in workers:
        priv_name = f'internal_{instance_id.replace("-", "_")}_private_key.pem'
        pub_name = f'internal_{instance_id.replace("-", "_")}_public_key.pem'
        priv_path = directory / priv_name
        pub_path = directory / pub_name

        if not priv_path.exists():
            if pub_path.exists():
                raise ValueError(f'configuration_invalid: public key exists without private key for {instance_id}')
            data = openssl('genpkey', '-algorithm', 'ED25519')
            fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)

        derived = openssl('pkey', '-in', str(priv_path), '-pubout')
        description = openssl('pkey', '-in', str(priv_path), '-text_pub', '-noout')
        if b'ED25519' not in description:
            raise ValueError(f'configuration_invalid: Ed25519 required for {instance_id}')

        if pub_path.exists():
            if pub_path.read_bytes().strip() != derived.strip():
                raise ValueError(f'configuration_invalid: public/private key mismatch for {instance_id}')
        else:
            fd = os.open(pub_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(derived)

        priv_path.chmod(0o600)
        pub_path.chmod(0o600)

        pub_pem = pub_path.read_text().strip()
        trust_registry[kid] = {
            "public_key_pem": pub_pem,
            "instance_id": instance_id,
            "principal": "ai_inference",
        }

    # Store internal_service_keys.json
    registry_path = directory / 'internal_service_keys.json'
    if not registry_path.exists():
        fd = os.open(registry_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(trust_registry, stream, indent=2)
    registry_path.chmod(0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('.local/persistence'))
    args = parser.parse_args()
    try:
        prepare(args.directory)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, ValueError) else 'configuration_invalid: internal key files')
    print('Internal Ed25519 worker keys and trust registry ready; no secret values printed.')

