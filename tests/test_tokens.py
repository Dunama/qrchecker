import time

from modules import _sign, make_token, verify_token


def test_make_and_verify_roundtrip():
    token = make_token("order-123")
    assert token["oid"] == "order-123"
    assert "sig" in token
    assert verify_token(token) is True


def test_tampered_payload_is_rejected():
    token = make_token("order-123")
    token["oid"] = "order-999"  # signature no longer matches
    assert verify_token(token) is False


def test_tampered_signature_is_rejected():
    token = make_token("order-123")
    token["sig"] = "0" * 64
    assert verify_token(token) is False


def test_expired_token_is_rejected():
    iat = int(time.time()) - 10_000
    exp = iat + 3600  # expired an hour+ ago
    import json

    body = json.dumps({"oid": "order-1", "iat": iat, "exp": exp}, sort_keys=True)
    token = {"oid": "order-1", "iat": iat, "exp": exp, "sig": _sign(body)}
    assert verify_token(token) is False


def test_malformed_token_is_rejected():
    assert verify_token({}) is False
    assert verify_token({"oid": "x"}) is False
