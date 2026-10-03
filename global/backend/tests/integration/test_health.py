def test_health_returns_ok_when_sqlite_is_reachable(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "database_role": "canonical_postgresql"}
