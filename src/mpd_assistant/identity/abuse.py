"""Anti-abuse for OTP delivery: country allowlist, per-number and per-IP limits, and a daily send cap (SMS pumping)."""

from dataclasses import dataclass
from typing import Iterable

import phonenumbers

from mpd_assistant.core.kv import KeyValueStore

DEFAULT_COUNTRIES = frozenset({"CA", "US"})
PER_NUMBER_PER_HOUR = 5
PER_IP_PER_HOUR = 20
DAILY_SEND_CAP = 500


class AbuseBlocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SmsAbuseGuard:
    kv: KeyValueStore
    countries: Iterable[str] = DEFAULT_COUNTRIES
    per_number: int = PER_NUMBER_PER_HOUR
    per_ip: int = PER_IP_PER_HOUR
    daily_cap: int = DAILY_SEND_CAP

    def check(self, phone_e164: str, client_ip: str | None) -> None:
        try:
            parsed = phonenumbers.parse(phone_e164, None)
            region = phonenumbers.region_code_for_number(parsed)
        except phonenumbers.NumberParseException:
            raise AbuseBlocked("invalid_number") from None
        if region not in set(self.countries):
            raise AbuseBlocked("country_not_allowed")
        if self.kv.incr(f"abuse:num:{phone_e164}", 3600) > self.per_number:
            raise AbuseBlocked("too_many_codes_for_number")
        if client_ip and self.kv.incr(f"abuse:ip:{client_ip}", 3600) > self.per_ip:
            raise AbuseBlocked("too_many_requests_from_address")
        from datetime import UTC, datetime

        day = datetime.now(UTC).strftime("%Y%m%d")
        if self.kv.incr(f"abuse:day:{day}", 86400) > self.daily_cap:
            raise AbuseBlocked("daily_send_cap_reached")
