"""Tests for the /config/keywords endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_keywords_starts_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/config/keywords")
    assert response.status_code == 200
    assert response.json() == []


def test_create_then_list(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/config/keywords",
        json={"term": "Rechnung", "locale": "de", "enabled": True, "weight": 1.5},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["term"] == "Rechnung"
    assert body["locale"] == "de"
    assert body["weight"] == 1.5

    listed = api_client.get("/api/v1/config/keywords").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_create_rejects_blank_term(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/config/keywords",
        json={"term": "", "locale": "en"},
    )
    assert response.status_code == 422


def test_update_replaces_fields(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/config/keywords",
        json={"term": "Vertrag", "locale": "de", "enabled": True, "weight": 1.0},
    ).json()

    updated = api_client.put(
        f"/api/v1/config/keywords/{created['id']}",
        json={"term": "Contract", "locale": "en", "enabled": False, "weight": 0.5},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["term"] == "Contract"
    assert body["enabled"] is False
    assert body["weight"] == 0.5


def test_update_unknown_returns_404(api_client: TestClient) -> None:
    response = api_client.put(
        "/api/v1/config/keywords/9999",
        json={"term": "x", "locale": "en", "enabled": True, "weight": 1.0},
    )
    assert response.status_code == 404


def test_delete_keyword(api_client: TestClient) -> None:
    created = api_client.post(
        "/api/v1/config/keywords",
        json={"term": "Mahnung", "locale": "de"},
    ).json()
    response = api_client.delete(f"/api/v1/config/keywords/{created['id']}")
    assert response.status_code == 204
    assert api_client.get("/api/v1/config/keywords").json() == []


def test_delete_unknown_returns_404(api_client: TestClient) -> None:
    response = api_client.delete("/api/v1/config/keywords/9999")
    assert response.status_code == 404
