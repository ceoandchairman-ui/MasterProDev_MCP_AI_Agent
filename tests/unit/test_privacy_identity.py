import logging

import pytest

from mpd_assistant.core import crypto
from mpd_assistant.core.logging import JsonFormatter, scrub
from mpd_assistant.identity.normalize import InvalidIdentifier, normalize_email, normalize_name, normalize_phone
from mpd_assistant.identity.otp import MAX_ATTEMPTS, OtpError, OtpService
from mpd_assistant.privacy.detector import CARD, EMAIL, PHONE, SIN, detect, luhn_valid, redact
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault


@pytest.fixture
def vault():
    return PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore(), allowlist=["info@masterprodev.com"])


def test_detects_core_types():
    text = "Mail ann@example.com or call (416) 555-0199. Card 4111 1111 1111 1111, SIN 046 454 286."
    types = {m.type for m in detect(text)}
    assert {EMAIL, PHONE, CARD, SIN} <= types


def test_luhn_rejects_random_digits():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert not any(m.type == CARD for m in detect("order 1234567890123456"))


def test_allowlist_keeps_company_contact():
    assert detect("write to info@masterprodev.com", allowlist=["info@masterprodev.com"]) == []


def test_redact_masks_values():
    assert redact("ann@example.com") == "[EMAIL]"


def test_vault_roundtrip_and_stability(vault):
    out1 = vault.tokenize("s1", "I am ann@example.com")
    out2 = vault.tokenize("s1", "again ann@example.com and bob@example.com")
    assert out1 == "I am <EMAIL_1>"
    assert out2 == "again <EMAIL_1> and <EMAIL_2>"
    assert vault.detokenize("s1", "send to <EMAIL_1>") == "send to ann@example.com"


def test_vault_isolates_sessions_and_unknown_tokens(vault):
    vault.tokenize("s1", "ann@example.com")
    assert vault.detokenize("s2", "<EMAIL_1>") == "<EMAIL_1>"
    assert vault.detokenize("s1", "<EMAIL_9>") == "<EMAIL_9>"


def test_vault_does_not_store_plaintext():
    store = MemoryVaultStore()
    v = PiiVault(crypto.FieldCipher(crypto.generate_key()), store)
    v.tokenize("s1", "ann@example.com")
    assert "ann@example.com" not in str(store.load("s1"))


def test_cipher_rotation():
    old, new = crypto.generate_key(), crypto.generate_key()
    token = crypto.FieldCipher(old).encrypt("secret")
    assert crypto.FieldCipher(new, old).decrypt(token) == "secret"


def test_blind_index_is_deterministic_and_keyed():
    k1, k2 = crypto.generate_key(), crypto.generate_key()
    assert crypto.blind_index(k1, "a@b.co") == crypto.blind_index(k1, "a@b.co")
    assert crypto.blind_index(k1, "a@b.co") != crypto.blind_index(k2, "a@b.co")


def test_normalizers():
    assert normalize_email("  Ann@Example.COM ") == "ann@example.com"
    assert normalize_phone("(416) 967-1111") == "+14169671111"
    assert normalize_phone("+1 416 967 1111") == "+14169671111"
    assert normalize_name("  Ann   Lee ") == "Ann Lee"
    for bad in ("not-an-email", "a@b", ""):
        with pytest.raises(InvalidIdentifier):
            normalize_email(bad)
    with pytest.raises(InvalidIdentifier):
        normalize_phone("123")
    with pytest.raises(InvalidIdentifier):
        normalize_name("<script>")


def test_otp_flow_and_limits():
    now = [1000.0]
    svc = OtpService("secret", clock=lambda: now[0])
    code = svc.issue("a@b.co")
    with pytest.raises(OtpError):
        svc.issue("a@b.co")
    assert not svc.verify("a@b.co", "000000" if code != "000000" else "111111")
    assert svc.verify("a@b.co", code)
    assert not svc.verify("a@b.co", code)  # single use


def test_otp_expiry_and_lockout():
    now = [0.0]
    svc = OtpService("secret", clock=lambda: now[0])
    code = svc.issue("x@y.co")
    now[0] += 601
    assert not svc.verify("x@y.co", code)
    code = svc.issue("x@y.co")
    for _ in range(MAX_ATTEMPTS):
        svc.verify("x@y.co", "999999" if code != "999999" else "888888")
    assert not svc.verify("x@y.co", code)


def test_log_scrubbing():
    assert "abcdefghijklmnopqrstuvwxyz123456" not in scrub("key hf_abcdefghijklmnopqrstuvwxyz123456")
    assert "abc123" not in scrub("password=abc123 ok")
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "Authorization: Bearer abcdefghijklmnopqrstuvwxyz", (), None)
    assert "abcdefghijklmnopqrstuvwxyz" not in JsonFormatter().format(rec)


def test_grouped_sin_is_flagged_even_with_wrong_check_digit():
    assert any(m.type == SIN for m in detect("my SIN is 123 456 789"))
    assert not any(m.type == SIN for m in detect("order 12345678"))
