from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_known_spa_deep_links_serve_index_without_capturing_protected_namespaces(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.html"
    index.write_text("<html><title>FAQ SPA</title></html>")
    client = TestClient(create_app(tmp_path))

    spa_paths = (
        "/",
        "/login",
        "/organization",
        "/inbox",
        "/p/project/i/initiative",
        "/a/ask/edit",
    )
    for path in spa_paths:
        response = client.get(path)
        assert response.status_code == 200
        assert "FAQ SPA" in response.text

    protected_paths = (
        "/api/not-a-route",
        "/r/not-a-token",
        "/d/not-a-decision",
        "/static/missing",
        "/admin",
        "/admin/path",
        "/jobs",
        "/jobs/path",
    )
    for path in protected_paths:
        response = client.get(path)
        assert response.status_code == 404
        assert "FAQ SPA" not in response.text
