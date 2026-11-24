"""The clean build is the oracle, so it must match spec.md. If these fail, every score lies."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

Auth = Callable[[str], dict[str, str]]


def _error_code(res: object) -> str:
    body = res.json()  # type: ignore[attr-defined]
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    return str(body["error"]["code"])


class TestAuth:
    def test_login_returns_token_and_user(self, client: TestClient) -> None:
        res = client.post("/auth/login", json={"username": "alice", "password": "alice-pass"})
        assert res.status_code == 200
        assert res.json()["user"] == {"id": 1, "username": "alice", "role": "fan"}
        assert res.json()["token"]

    def test_wrong_password_is_401(self, client: TestClient) -> None:
        res = client.post("/auth/login", json={"username": "alice", "password": "nope"})
        assert res.status_code == 401
        assert _error_code(res) == "invalid_credentials"

    @pytest.mark.parametrize("header", [None, "Token abc", "Bearer unknown"])
    def test_protected_endpoint_rejects_bad_token(
        self, client: TestClient, header: str | None
    ) -> None:
        headers = {"Authorization": header} if header else {}
        res = client.get("/orders", headers=headers)
        assert res.status_code == 401
        assert _error_code(res) == "unauthorized"


class TestEvents:
    def test_pages_are_disjoint_and_complete(self, client: TestClient) -> None:
        ids: list[int] = []
        for page in (1, 2, 3):
            body = client.get(f"/events?page={page}&pageSize=5").json()
            ids += [e["id"] for e in body["items"]]
            assert body["total"] == 12
        assert ids == list(range(1, 13))

    @pytest.mark.parametrize("query", ["page=0", "pageSize=0", "pageSize=51", "page=abc"])
    def test_invalid_paging_is_400(self, client: TestClient, query: str) -> None:
        res = client.get(f"/events?{query}")
        assert res.status_code == 400
        assert _error_code(res) == "validation_error"

    def test_unknown_event_uses_error_envelope(self, client: TestClient) -> None:
        res = client.get("/events/9999")
        assert res.status_code == 404
        assert _error_code(res) == "not_found"

    def test_unknown_route_uses_error_envelope(self, client: TestClient) -> None:
        res = client.get("/nope")
        assert res.status_code == 404
        assert _error_code(res) == "not_found"


class TestCreateOrder:
    @pytest.mark.parametrize("quantity", [0, 7, -1])
    def test_quantity_outside_1_to_6_is_400(
        self, client: TestClient, auth: Auth, quantity: int
    ) -> None:
        res = client.post(
            "/orders", headers=auth("alice"), json={"eventId": 2, "quantity": quantity}
        )
        assert res.status_code == 400
        assert _error_code(res) == "invalid_quantity"

    def test_string_quantity_is_rejected(self, client: TestClient, auth: Auth) -> None:
        res = client.post("/orders", headers=auth("alice"), json={"eventId": 2, "quantity": "2"})
        assert res.status_code == 400
        assert _error_code(res) == "validation_error"

    def test_success_decrements_remaining(self, client: TestClient, auth: Auth) -> None:
        res = client.post("/orders", headers=auth("alice"), json={"eventId": 2, "quantity": 6})
        assert res.status_code == 201
        assert res.json()["totalCents"] == 45000
        assert client.get("/events/2").json()["remaining"] == 294

    def test_fan10_rounds_half_up(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 1, "quantity": 1, "promoCode": "FAN10"}
        order = client.post("/orders", headers=auth("alice"), json=body).json()
        assert (order["discountCents"], order["totalCents"]) == (500, 4499)

    def test_welcome5_is_single_use_per_user(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 2, "quantity": 1, "promoCode": "WELCOME5"}
        headers = auth("alice")
        assert client.post("/orders", headers=headers, json=body).status_code == 201
        second = client.post("/orders", headers=headers, json=body)
        assert second.status_code == 400
        assert _error_code(second) == "promo_already_used"
        assert client.post("/orders", headers=auth("bob"), json=body).status_code == 201

    def test_discount_is_capped_at_subtotal(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 3, "quantity": 1, "promoCode": "WELCOME5"}
        order = client.post("/orders", headers=auth("alice"), json=body).json()
        assert (order["discountCents"], order["totalCents"]) == (300, 0)

    def test_unknown_promo_is_400(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 2, "quantity": 1, "promoCode": "fan10"}
        res = client.post("/orders", headers=auth("alice"), json=body)
        assert res.status_code == 400
        assert _error_code(res) == "invalid_promo_code"

    def test_cannot_buy_more_than_remaining(self, client: TestClient, auth: Auth) -> None:
        res = client.post("/orders", headers=auth("alice"), json={"eventId": 11, "quantity": 6})
        assert res.status_code == 409
        assert _error_code(res) == "sold_out"
        ok = client.post("/orders", headers=auth("alice"), json={"eventId": 11, "quantity": 5})
        assert ok.status_code == 201
        assert client.get("/events/11").json()["remaining"] == 0


class TestOrderAccess:
    def test_other_users_order_is_404(self, client: TestClient, auth: Auth) -> None:
        oid = client.post(
            "/orders", headers=auth("alice"), json={"eventId": 2, "quantity": 1}
        ).json()["id"]
        res = client.get(f"/orders/{oid}", headers=auth("bob"))
        assert res.status_code == 404
        assert client.get(f"/orders/{oid}", headers=auth("admin")).status_code == 200

    def test_fans_list_only_their_orders(self, client: TestClient, auth: Auth) -> None:
        client.post("/orders", headers=auth("alice"), json={"eventId": 2, "quantity": 1})
        client.post("/orders", headers=auth("bob"), json={"eventId": 2, "quantity": 1})
        assert len(client.get("/orders", headers=auth("alice")).json()["items"]) == 1
        assert len(client.get("/orders", headers=auth("admin")).json()["items"]) == 2


class TestCancel:
    def test_cancel_restocks_once(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice")
        oid = client.post("/orders", headers=headers, json={"eventId": 5, "quantity": 2}).json()[
            "id"
        ]
        res = client.post(f"/orders/{oid}/cancel", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"
        assert client.get("/events/5").json()["remaining"] == 100

        again = client.post(f"/orders/{oid}/cancel", headers=headers)
        assert again.status_code == 409
        assert _error_code(again) == "already_cancelled"
        assert client.get("/events/5").json()["remaining"] == 100

    def test_non_owner_cannot_cancel(self, client: TestClient, auth: Auth) -> None:
        oid = client.post(
            "/orders", headers=auth("alice"), json={"eventId": 5, "quantity": 1}
        ).json()["id"]
        assert client.post(f"/orders/{oid}/cancel", headers=auth("bob")).status_code == 404
