#!/usr/bin/env python3
"""Rotate SECRET_KEY and re-encrypt certificate private keys.

SECRET_KEY derives the Fernet key that encrypts ``certificates.key_pem``
(see app/services/crypto_service.py). Changing SECRET_KEY without re-encrypting
those values silently breaks TLS on every edge node, because the decrypt path
falls back to returning the ciphertext as if it were plaintext.

Usage (run on the control-plane host, in the venv, with the app's .env loaded):

    # 1. Generate a new secret
    NEW=$(openssl rand -hex 48)

    # 2. Dry-run: check every encrypted key can be read with the CURRENT SECRET_KEY
    python scripts/rotate_secret_key.py --new "$NEW" --dry-run

    # 3. Re-encrypt in the DB (old key read from the current SECRET_KEY env)
    python scripts/rotate_secret_key.py --new "$NEW"

    # 4. Set SECRET_KEY=$NEW in .env, then restart: cdn_app cdn_celery cdn_celery_beat

The OLD key defaults to the current ``settings.SECRET_KEY``; override with --old.
Nothing is written in --dry-run. On any decrypt failure the whole run aborts
before writing, so a wrong --old can't corrupt data.
"""
import argparse
import asyncio
import base64
import hashlib
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

# Ensure the project root is importable when run as `python scripts/...`.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.certificate import Certificate  # noqa: E402

ENCRYPTED_PREFIX = "ENC:"


def _fernet(secret: str) -> Fernet:
    derived = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate SECRET_KEY, re-encrypt cert keys")
    parser.add_argument("--new", required=True, help="new SECRET_KEY value")
    parser.add_argument("--old", default=settings.SECRET_KEY, help="current SECRET_KEY (default: from settings)")
    parser.add_argument("--dry-run", action="store_true", help="verify only, write nothing")
    args = parser.parse_args()

    if args.new == args.old:
        print("new and old SECRET_KEY are identical; nothing to do", file=sys.stderr)
        return 1

    old_f = _fernet(args.old)
    new_f = _fernet(args.new)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Certificate))).scalars().all()
        pending = []
        for cert in rows:
            val = cert.key_pem
            if not val or not val.startswith(ENCRYPTED_PREFIX):
                continue  # plaintext or empty — leave as-is
            token = val[len(ENCRYPTED_PREFIX):].encode("ascii")
            try:
                plaintext = old_f.decrypt(token)
            except InvalidToken:
                print(
                    f"ABORT: certificate id={cert.id} ({cert.common_name}) cannot be "
                    f"decrypted with the provided --old key. Nothing was written.",
                    file=sys.stderr,
                )
                return 2
            reencrypted = ENCRYPTED_PREFIX + new_f.encrypt(plaintext).decode("ascii")
            pending.append((cert, reencrypted))

        print(f"{len(pending)} encrypted certificate key(s) can be re-encrypted.")
        if args.dry_run:
            print("dry-run: no changes written.")
            return 0

        for cert, reencrypted in pending:
            cert.key_pem = reencrypted
        await session.commit()
        print(f"Re-encrypted {len(pending)} key(s). Now set SECRET_KEY to the new value "
              "in .env and restart cdn_app cdn_celery cdn_celery_beat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
