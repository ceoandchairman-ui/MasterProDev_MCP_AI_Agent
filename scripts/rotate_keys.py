"""Operator tool for key rotation. Dry run unless --apply is given. See docs/runbooks/key-rotation.md.

  python scripts/rotate_keys.py encryption                       re-encrypt fields under the current DATA_ENCRYPTION_KEY
  python scripts/rotate_keys.py blind-index --new-key <key>      recompute lookup indexes under a new BLIND_INDEX_KEY
  add --apply to write the changes

Back up the database first (scripts/backup_postgres.sh).
"""

import argparse

from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.db import make_engine
from mpd_assistant.privacy.rotation import rotate_blind_indexes, rotate_encryption


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=["encryption", "blind-index"])
    parser.add_argument("--new-key", help="the new BLIND_INDEX_KEY (blind-index only)")
    parser.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    args = parser.parse_args()

    s = get_settings()
    s.require_crypto_keys()
    engine = make_engine(s.DATABASE_URL)
    cipher = FieldCipher(*s.cipher_keys())
    if args.what == "encryption":
        report = rotate_encryption(engine, cipher, dry_run=not args.apply)
    else:
        if not args.new_key:
            raise SystemExit("--new-key is required for blind-index")
        report = rotate_blind_indexes(engine, cipher, args.new_key, dry_run=not args.apply)

    print(f"{'DRY RUN' if report.dry_run else 'APPLIED'}: scanned={report.scanned} rotated={report.rotated} already_current={report.already_current} failed={len(report.failed)}")
    for row_id in report.failed:
        print("  could not process row", row_id)
    return 0 if report.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
