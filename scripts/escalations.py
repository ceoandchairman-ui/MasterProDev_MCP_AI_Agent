"""Operator tool for escalations.

  python scripts/escalations.py list
  python scripts/escalations.py resolve <reference>

Resolving an escalation lets the assistant answer that conversation again.
"""

import sys

from mpd_assistant.business.escalations import EscalationService
from mpd_assistant.business.escalations_sql import SqlEscalationRepository
from mpd_assistant.core.config import get_settings
from mpd_assistant.core.db import make_engine


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "resolve"):
        raise SystemExit(__doc__)
    repo = SqlEscalationRepository(make_engine(get_settings().DATABASE_URL))
    if sys.argv[1] == "list":
        for e in repo.list_open():
            print(f"{e.reference}  {e.created_at:%Y-%m-%d %H:%M}  {e.reason}\n{e.summary}\n")
        return
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print("resolved" if EscalationService(repo=repo).resolve(sys.argv[2]) else "not found or already resolved")


if __name__ == "__main__":
    main()
