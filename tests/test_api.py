def scan(client, token, role, notes=None):
    return client.post(
        "/scan",
        json={"qr_token": token, "role": role, "notes": notes},
    )


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_order_returns_token_and_qr(order):
    assert order["order_id"]
    assert order["qr_token"]["oid"] == order["order_id"]
    assert order["qr_image_b64"]  # base64 PNG string


def test_full_lifecycle(client, order):
    token = order["qr_token"]

    r1 = scan(client, token, "seller")
    assert r1.status_code == 200
    assert r1.json()["event"] == "ITEM_COLLECTED"

    r2 = scan(client, token, "hotel", notes="stain on sleeve")
    assert r2.json()["event"] == "DRY_CLEAN_IN"

    r3 = scan(client, token, "hotel")
    assert r3.json()["event"] == "DRY_CLEAN_OUT"

    r4 = scan(client, token, "logistics")
    assert r4.json()["event"] == "DELIVERED"


def test_wrong_role_is_blocked_not_advanced(client, order):
    token = order["qr_token"]
    # Logistics cannot act while the item is still CONFIRMED.
    resp = scan(client, token, "logistics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is True
    assert body["reason_code"] == "ROLE_NO_ACTION"
    assert body["current_stage"] == "CONFIRMED"


def test_renter_is_read_only(client, order):
    token = order["qr_token"]
    resp = scan(client, token, "renter")
    assert resp.status_code == 200
    body = resp.json()
    assert "timeline" in body
    assert body["current_stage"] == "CONFIRMED"  # unchanged


def test_hotel_notes_are_recorded(client, order):
    token = order["qr_token"]
    scan(client, token, "seller")
    scan(client, token, "hotel", notes="loose button")

    timeline = client.get(f"/orders/{order['order_id']}/timeline").json()
    notes = [e.get("notes") for e in timeline["events"]]
    assert "loose button" in notes


def test_invalid_token_rejected(client):
    bad = {"oid": "nope", "iat": 0, "exp": 0, "sig": "bad"}
    resp = scan(client, bad, "seller")
    assert resp.status_code == 403


def test_revoked_order_cannot_be_scanned(client, order):
    token = order["qr_token"]
    order_id = order["order_id"]

    revoke = client.post(f"/orders/{order_id}/revoke", json={"reason": "lost item"})
    assert revoke.status_code == 200

    resp = scan(client, token, "seller")
    assert resp.status_code == 403


def test_timeline_not_found(client):
    resp = client.get("/orders/does-not-exist/timeline")
    assert resp.status_code == 404


def test_request_id_header_is_returned(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")
    assert resp.json()["request_id"]
