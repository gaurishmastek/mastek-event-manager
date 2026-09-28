from app.main import PUBLIC_ROUTES, app


def _routes():
    # The OpenAPI schema lists every API route, including those from included routers.
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            yield method.upper(), path


def test_every_non_public_route_requires_authentication(client):
    """Guards the deny-by-default rule: a new route must be added to PUBLIC_ROUTES on purpose."""
    checked = 0
    for method, path in _routes():
        if (method, path) in PUBLIC_ROUTES:
            continue
        url = path.replace("{event_id}", "1").replace("{user_id}", "1")
        response = client.request(method, url, json={})
        assert response.status_code == 401, f"{method} {path} is reachable without a token"
        checked += 1
    assert checked > 0


def test_public_routes_still_exist():
    assert PUBLIC_ROUTES <= set(_routes())


def test_security_headers_are_set(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
