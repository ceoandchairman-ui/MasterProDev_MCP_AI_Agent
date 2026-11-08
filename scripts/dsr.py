"""Operator tool for data-subject requests. Requires the production environment variables.

  python scripts/dsr.py export <user_id>
  python scripts/dsr.py erase <user_id>

Erasure is permanent. Confirm the identity of the requester first (see S21.9).
"""

import json
import sys

from mpd_assistant.core.config import get_settings
from mpd_assistant.core.crypto import FieldCipher
from mpd_assistant.core.db import make_engine
from mpd_assistant.core.kv import RedisKV
from mpd_assistant.privacy.dsr import DataSubjectService


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "erase"):
        raise SystemExit(__doc__)
    s = get_settings()
    import redis

    kv = RedisKV(redis.Redis.from_url(s.REDIS_URL))
    service = DataSubjectService(make_engine(s.DATABASE_URL), kv, FieldCipher(*s.cipher_keys()), s.BLIND_INDEX_KEY)
    user_id = sys.argv[2]
    if sys.argv[1] == "export":
        print(json.dumps(service.export(user_id), indent=2, default=str))
    else:
        report = service.erase(user_id)
        print(json.dumps({"complete": report.complete, "deleted": report.deleted, "kv_keys_removed": report.kv_keys_removed,
                          "vendors_to_notify": report.vendors_to_notify, "errors": report.errors}, indent=2))


if __name__ == "__main__":
    main()
