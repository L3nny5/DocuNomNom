"""Tests for the SPA / static-file serving layer.

Covers the regression reported in production where
``GET /`` and ``GET /index.html`` returned 404 because no frontend was
mounted even though ``/app/frontend-dist`` existed inside the image.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docunomnom.api.frontend import FRONTEND_DIST_ENV, resolve_frontend_dist
from docunomnom.api.main import create_app

INDEX_HTML = (
    "<!doctype html>\n"
    "<html><head><title>DocuNomNom</title></head>"
    "<body><div id='root'></div>"
    "<script type='module' src='/assets/index.js'></script>"
    "</body></html>\n"
)

ASSET_JS = "export const stub = 'ok';\n"
ASSET_CSS = ":root { --ok: 1; }\n"
FAVICON_BYTES = b"\x00\x00favicon-stub"


@pytest.fixture
def frontend_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal Vite-style ``dist/`` layout and point the API at it."""
    dist = tmp_path / "frontend-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index.js").write_text(ASSET_JS, encoding="utf-8")
    (dist / "assets" / "index.css").write_text(ASSET_CSS, encoding="utf-8")
    (dist / "favicon.ico").write_bytes(FAVICON_BYTES)
    monkeypatch.setenv(FRONTEND_DIST_ENV, str(dist))
    return dist


@pytest.fixture
def client_with_frontend(frontend_dist: Path) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_root_serves_index_html(client_with_frontend: TestClient) -> None:
    response = client_with_frontend.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id='root'></div>" in response.text


def test_assets_are_served_with_correct_content_type(
    client_with_frontend: TestClient,
) -> None:
    js = client_with_frontend.get("/assets/index.js")
    assert js.status_code == 200
    assert js.text == ASSET_JS
    assert "javascript" in js.headers["content-type"]

    css = client_with_frontend.get("/assets/index.css")
    assert css.status_code == 200
    assert css.text == ASSET_CSS
    assert "css" in css.headers["content-type"]


def test_top_level_static_file_is_served(client_with_frontend: TestClient) -> None:
    """Files that live at the bundle root (favicon.ico, robots.txt, ...)
    must be served as themselves, not as the SPA shell."""
    response = client_with_frontend.get("/favicon.ico")
    assert response.status_code == 200
    assert response.content == FAVICON_BYTES


@pytest.mark.parametrize(
    "spa_path",
    [
        "/jobs",
        "/history",
        "/config",
        "/keywords",
        "/review/42",
        "/review/abc/deep/nested",
    ],
)
def test_spa_client_routes_fall_back_to_index_html(
    client_with_frontend: TestClient, spa_path: str
) -> None:
    """Hard refresh on a client-side route must render the SPA shell so
    the React router can take over."""
    response = client_with_frontend.get(spa_path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id='root'></div>" in response.text


def test_api_routes_are_not_shadowed_by_spa(client_with_frontend: TestClient) -> None:
    """The SPA catch-all must never hijack ``/api/v1/*`` — existing
    endpoints must keep returning JSON."""
    response = client_with_frontend.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_unknown_api_route_returns_json_404_not_html(
    client_with_frontend: TestClient,
) -> None:
    """Regression guard: a missing API path must NOT fall back to
    index.html — API clients must see a proper JSON 404."""
    response = client_with_frontend.get("/api/v1/definitely-not-a-route")
    assert response.status_code == 404
    content_type = response.headers["content-type"]
    assert content_type.startswith("application/json"), (
        f"API 404 leaked as HTML (content-type={content_type!r}); the SPA "
        "catch-all is shadowing the API router."
    )


def test_path_traversal_is_rejected(client_with_frontend: TestClient) -> None:
    """``../`` segments that would escape the bundle directory must not
    expose files on the host."""
    response = client_with_frontend.get("/../../etc/passwd")
    # TestClient collapses ``..`` segments client-side before sending,
    # so also exercise the server-side guard directly.
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        # Collapsed to "/" by the client → SPA shell, not /etc/passwd.
        assert "<div id='root'></div>" in response.text


def test_openapi_and_docs_remain_accessible(client_with_frontend: TestClient) -> None:
    """The API's OpenAPI / Swagger surface lives under ``/api/v1`` and
    must not be swallowed by the SPA."""
    openapi = client_with_frontend.get("/api/v1/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "DocuNomNom"

    docs = client_with_frontend.get("/api/v1/docs")
    assert docs.status_code == 200


def test_missing_bundle_is_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no bundle is present the app must still boot API-only —
    this is how the test suite and the dev setup run."""
    monkeypatch.setenv(FRONTEND_DIST_ENV, str(tmp_path / "does-not-exist"))
    assert resolve_frontend_dist() is None

    app = create_app()
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        # No SPA mount -> root has no handler -> plain 404 (from Starlette).
        assert c.get("/").status_code == 404


def test_partial_bundle_without_index_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dist/ directory without index.html must be ignored rather than
    half-served."""
    incomplete = tmp_path / "frontend-dist"
    (incomplete / "assets").mkdir(parents=True)
    (incomplete / "assets" / "index.js").write_text(ASSET_JS, encoding="utf-8")
    monkeypatch.setenv(FRONTEND_DIST_ENV, str(incomplete))
    assert resolve_frontend_dist() is None
