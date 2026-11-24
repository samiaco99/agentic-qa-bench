from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from qabench.target import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth(client: TestClient) -> Callable[[str], dict[str, str]]:
    def _auth(username: str) -> dict[str, str]:
        res = client.post(
            "/auth/login", json={"username": username, "password": f"{username}-pass"}
        )
        assert res.status_code == 200
        return {"Authorization": f"Bearer {res.json()['token']}"}

    return _auth
