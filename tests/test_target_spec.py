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


def _order(client: TestClient, headers: dict[str, str], **body: object) -> dict[str, object]:
    res = client.post("/orders", headers=headers, json=body)
    assert res.status_code == 201, res.json()
    return dict(res.json())


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

    def test_earlier_tokens_stay_valid_after_a_new_login(
        self, client: TestClient, auth: Auth
    ) -> None:
        first, second = auth("alice"), auth("alice")
        assert first != second
        assert client.get("/orders", headers=first).status_code == 200
        assert client.get("/orders", headers=second).status_code == 200

    def test_logout_revokes_only_the_presented_token(self, client: TestClient, auth: Auth) -> None:
        first, second = auth("alice"), auth("alice")
        res = client.post("/auth/logout", headers=first)
        assert (res.status_code, res.content) == (204, b"")
        revoked = client.get("/orders", headers=first)
        assert revoked.status_code == 401
        assert _error_code(revoked) == "unauthorized"
        assert client.get("/orders", headers=second).status_code == 200


class TestEvents:
    def test_pages_are_disjoint_and_complete(self, client: TestClient) -> None:
        ids: list[int] = []
        for page in (1, 2, 3):
            body = client.get(f"/events?page={page}&pageSize=5").json()
            ids += [e["id"] for e in body["items"]]
            assert body["total"] == 13
        assert ids == list(range(1, 14))

    def test_page_after_the_last_is_empty(self, client: TestClient) -> None:
        res = client.get("/events?page=3&pageSize=10")
        assert res.status_code == 200
        assert res.json()["items"] == []

    def test_sold_out_and_closed_events_are_listed(self, client: TestClient, auth: Auth) -> None:
        _order(client, auth("alice"), eventId=11, quantity=5)
        body = client.get("/events?pageSize=50").json()
        events = {e["id"]: e for e in body["items"]}
        assert body["total"] == len(events) == 13
        assert events[11]["remaining"] == 0
        assert events[13]["salesOpen"] is False

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
        assert (res.json()["feeCents"], res.json()["totalCents"]) == (600, 45600)
        assert res.json()["refundCents"] is None
        assert client.get("/events/2").json()["remaining"] == 294

    def test_fee_is_150_per_ticket_below_the_cap(self, client: TestClient, auth: Auth) -> None:
        order = _order(client, auth("alice"), eventId=2, quantity=2)
        assert (order["feeCents"], order["totalCents"]) == (300, 15300)

    def test_fan10_rounds_half_up(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 1, "quantity": 1, "promoCode": "FAN10"}
        order = client.post("/orders", headers=auth("alice"), json=body).json()
        assert (order["discountCents"], order["feeCents"], order["totalCents"]) == (500, 150, 4649)

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
        assert (order["discountCents"], order["totalCents"]) == (300, 150)

    def test_unknown_promo_is_400(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 2, "quantity": 1, "promoCode": "fan10"}
        res = client.post("/orders", headers=auth("alice"), json=body)
        assert res.status_code == 400
        assert _error_code(res) == "invalid_promo_code"

    @pytest.mark.parametrize("promo", [None, "FAN10"])
    def test_closed_sales_reject_orders(
        self, client: TestClient, auth: Auth, promo: str | None
    ) -> None:
        body = {"eventId": 13, "quantity": 1, "promoCode": promo}
        res = client.post("/orders", headers=auth("alice"), json=body)
        assert res.status_code == 409
        assert _error_code(res) == "sales_closed"

    def test_ticket_limit_is_8_per_user_per_event(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice")
        _order(client, headers, eventId=5, quantity=6)
        res = client.post("/orders", headers=headers, json={"eventId": 5, "quantity": 3})
        assert res.status_code == 409
        assert _error_code(res) == "ticket_limit_exceeded"
        _order(client, headers, eventId=5, quantity=2)
        _order(client, auth("bob"), eventId=5, quantity=6)

    def test_cancelled_orders_do_not_count_towards_the_limit(
        self, client: TestClient, auth: Auth
    ) -> None:
        headers = auth("alice")
        first = _order(client, headers, eventId=5, quantity=6)
        assert client.post(f"/orders/{first['id']}/cancel", headers=headers).status_code == 200
        _order(client, headers, eventId=5, quantity=6)
        _order(client, headers, eventId=5, quantity=2)

    def test_cannot_buy_more_than_remaining(self, client: TestClient, auth: Auth) -> None:
        res = client.post("/orders", headers=auth("alice"), json={"eventId": 11, "quantity": 6})
        assert res.status_code == 409
        assert _error_code(res) == "sold_out"
        ok = client.post("/orders", headers=auth("alice"), json={"eventId": 11, "quantity": 5})
        assert ok.status_code == 201
        assert client.get("/events/11").json()["remaining"] == 0


class TestIdempotency:
    def test_replay_returns_the_original_order_and_changes_nothing(
        self, client: TestClient, auth: Auth
    ) -> None:
        headers = auth("alice") | {"Idempotency-Key": "retry-1"}
        body = {"eventId": 2, "quantity": 2, "promoCode": "WELCOME5"}
        first = client.post("/orders", headers=headers, json=body)
        replay = client.post("/orders", headers=headers, json=body)
        assert (first.status_code, replay.status_code) == (201, 200)
        assert replay.json() == first.json()
        assert client.get("/events/2").json()["remaining"] == 298
        assert len(client.get("/orders", headers=headers).json()["items"]) == 1

    def test_same_key_with_a_different_body_is_409(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice") | {"Idempotency-Key": "retry-1"}
        client.post("/orders", headers=headers, json={"eventId": 2, "quantity": 1})
        res = client.post("/orders", headers=headers, json={"eventId": 2, "quantity": 2})
        assert res.status_code == 409
        assert _error_code(res) == "idempotency_conflict"

    def test_keys_are_scoped_per_user(self, client: TestClient, auth: Auth) -> None:
        body = {"eventId": 2, "quantity": 1}
        alice = client.post("/orders", headers=auth("alice") | {"Idempotency-Key": "k"}, json=body)
        bob = client.post("/orders", headers=auth("bob") | {"Idempotency-Key": "k"}, json=body)
        assert (alice.status_code, bob.status_code) == (201, 201)
        assert bob.json()["userId"] == 2
        assert bob.json()["id"] != alice.json()["id"]

    def test_a_failed_request_does_not_store_the_key(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice") | {"Idempotency-Key": "k"}
        failed = client.post("/orders", headers=headers, json={"eventId": 11, "quantity": 6})
        assert failed.status_code == 409
        ok = client.post("/orders", headers=headers, json={"eventId": 2, "quantity": 1})
        assert ok.status_code == 201

    @pytest.mark.parametrize("key", ["", "k" * 65])
    def test_key_length_is_validated(self, client: TestClient, auth: Auth, key: str) -> None:
        headers = auth("alice") | {"Idempotency-Key": key}
        res = client.post("/orders", headers=headers, json={"eventId": 2, "quantity": 1})
        assert res.status_code == 400
        assert _error_code(res) == "validation_error"


class TestUpdateEvent:
    def test_admin_changes_price_and_capacity(self, client: TestClient, auth: Auth) -> None:
        _order(client, auth("alice"), eventId=5, quantity=3)
        res = client.patch("/events/5", headers=auth("admin"), json={"capacity": 120})
        assert res.status_code == 200
        assert (res.json()["capacity"], res.json()["remaining"]) == (120, 117)
        res = client.patch("/events/5", headers=auth("admin"), json={"priceCents": 0})
        assert res.json()["priceCents"] == 0

    def test_fan_is_forbidden(self, client: TestClient, auth: Auth) -> None:
        res = client.patch("/events/1", headers=auth("alice"), json={"priceCents": 100})
        assert res.status_code == 403
        assert _error_code(res) == "forbidden"
        assert client.get("/events/1").json()["priceCents"] == 4999

    def test_capacity_cannot_drop_below_sold(self, client: TestClient, auth: Auth) -> None:
        _order(client, auth("alice"), eventId=11, quantity=4)
        res = client.patch("/events/11", headers=auth("admin"), json={"capacity": 3})
        assert res.status_code == 409
        assert _error_code(res) == "capacity_below_sold"
        ok = client.patch("/events/11", headers=auth("admin"), json={"capacity": 4})
        assert ok.json()["remaining"] == 0

    @pytest.mark.parametrize(
        "body", [{}, {"priceCents": -1}, {"capacity": 0}, {"priceCents": "100"}, {"name": "x"}]
    )
    def test_invalid_body_is_400(
        self, client: TestClient, auth: Auth, body: dict[str, object]
    ) -> None:
        res = client.patch("/events/1", headers=auth("admin"), json=body)
        assert res.status_code == 400
        assert _error_code(res) == "validation_error"

    def test_unknown_event_is_404(self, client: TestClient, auth: Auth) -> None:
        res = client.patch("/events/9999", headers=auth("admin"), json={"priceCents": 1})
        assert res.status_code == 404
        assert _error_code(res) == "not_found"

    def test_price_change_does_not_touch_existing_orders(
        self, client: TestClient, auth: Auth
    ) -> None:
        headers = auth("alice")
        before = _order(client, headers, eventId=2, quantity=1, promoCode="FAN10")
        client.patch("/events/2", headers=auth("admin"), json={"priceCents": 8000})
        assert client.get(f"/orders/{before['id']}", headers=headers).json() == before
        after = _order(client, headers, eventId=2, quantity=1)
        assert after["unitPriceCents"] == 8000


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

    def test_refund_excludes_the_fee(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice")
        order = _order(client, headers, eventId=2, quantity=1, promoCode="FAN10")
        assert (order["discountCents"], order["totalCents"]) == (750, 6900)
        cancelled = client.post(f"/orders/{order['id']}/cancel", headers=headers).json()
        assert cancelled["refundCents"] == 6750

    def test_cancelled_orders_stay_listed(self, client: TestClient, auth: Auth) -> None:
        headers = auth("alice")
        order = _order(client, headers, eventId=2, quantity=1)
        client.post(f"/orders/{order['id']}/cancel", headers=headers)
        items = client.get("/orders", headers=headers).json()["items"]
        assert [(o["id"], o["status"]) for o in items] == [(order["id"], "cancelled")]
