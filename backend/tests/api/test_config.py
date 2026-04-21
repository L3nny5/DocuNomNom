"""Tests for the /config endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_config_returns_settings_and_empty_overrides(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert "settings" in body
    assert body["overrides"] == {}
    assert body["overrides_hash"] != ""
    assert body["settings"]["ocr_backend"] in ("ocrmypdf", "external_api")


def test_put_config_persists_overrides(api_client: TestClient) -> None:
    payload = {
        "splitter_keyword_weight": 0.7,
        "splitter_auto_export_threshold": 0.8,
        "archive_after_export": False,
    }
    put = api_client.put("/api/v1/config", json=payload)
    assert put.status_code == 200
    body = put.json()
    assert body["overrides"] == payload

    get = api_client.get("/api/v1/config").json()
    assert get["overrides"] == payload
    assert get["overrides_hash"] == body["overrides_hash"]


def test_put_config_rejects_unknown_fields(api_client: TestClient) -> None:
    response = api_client.put("/api/v1/config", json={"not_a_field": 1})
    assert response.status_code == 422


def test_put_config_validates_ranges(api_client: TestClient) -> None:
    response = api_client.put(
        "/api/v1/config",
        json={"splitter_keyword_weight": 5.0},
    )
    assert response.status_code == 422


def test_put_config_replaces_overrides(api_client: TestClient) -> None:
    api_client.put("/api/v1/config", json={"archive_after_export": True})
    second = api_client.put("/api/v1/config", json={"splitter_min_pages_per_part": 2})
    body = second.json()
    assert body["overrides"] == {"splitter_min_pages_per_part": 2}
