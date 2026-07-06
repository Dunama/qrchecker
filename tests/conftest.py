import pytest
from fastapi.testclient import TestClient

import modules
from main import app


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the in-memory stores before every test for isolation."""
    modules.orders_db.clear()
    modules.events_db.clear()
    yield
    modules.orders_db.clear()
    modules.events_db.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def order(client):
    """Create an order and return the parsed response body."""
    resp = client.post("/orders", json={"item_code": "DRESS-001"})
    assert resp.status_code == 200
    return resp.json()
