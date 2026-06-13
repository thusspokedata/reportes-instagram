from app import create_app


def test_health_returns_ok(env):
    app = create_app()
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_root_redirects_to_dashboard(env):
    # El dominio pelado no debe dar 404: redirige al dashboard (que a su vez
    # manda a login si no hay sesión).
    app = create_app()
    response = app.test_client().get("/")

    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]
