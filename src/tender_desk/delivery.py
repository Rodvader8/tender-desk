"""Send an approved quote to an outside system without ever sending it twice or believing a guess.

The failure this exists for: the request goes out, the other side applies it, and the answer is lost (a timeout, a
dropped connection, a 503 from a gateway in front). From here that looks exactly like a request that never arrived.
The rules:

  * One delivery row per quote and one idempotency key per delivery, so repeating the request is safe on both sides.
  * After any ambiguous failure, ask the other side what it holds (an authoritative readback) BEFORE sending again.
  * Only the other side's own record can make a delivery `sent`, and only if it matches exactly what was approved.
  * If even the readback fails, the state is `unknown`. Nothing is resent blind and nothing is called sent.
    `reconcile` settles it later, readback first.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .graph import audit

log = logging.getLogger("tender_desk.delivery")
COLUMNS = "quote_id, tender_id, idempotency_key, state, reference, attempts, last_error"


class DeliveryAmbiguous(Exception):
    """The request may or may not have been applied: a timeout, a lost connection, or a server error."""


class DeliveryRejected(Exception):
    """The other side clearly refused the request. Repeating it would be refused again."""


class PortalClient:
    """Talks to the portal over any HTTP client with a `request(method, url, **kw)` method (httpx.Client, TestClient)."""

    def __init__(self, http: Any, base_url: str = "") -> None:
        self.http, self.base = http, base_url.rstrip("/")

    def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self.http.request(method, self.base + path, **kw)
        except httpx.TransportError as e:  # timeouts, refused or dropped connections: we cannot know what happened
            raise DeliveryAmbiguous(type(e).__name__) from e
        if r.status_code >= 500:
            raise DeliveryAmbiguous(f"HTTP {r.status_code}")
        return r

    def submit(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._call("POST", "/submissions", json=payload, headers={"Idempotency-Key": key})
        if r.status_code >= 400:
            raise DeliveryRejected(f"portal refused: HTTP {r.status_code}")
        return r.json()

    def lookup(self, key: str) -> dict[str, Any] | None:
        r = self._call("GET", f"/submissions/{key}")
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise DeliveryRejected(f"portal refused the readback: HTTP {r.status_code}")
        return r.json()


def _row(conn, quote_id: int) -> dict[str, Any] | None:
    r = conn.execute(f"SELECT {COLUMNS} FROM deliveries WHERE quote_id=%s", (quote_id,)).fetchone()  # noqa: S608 constant list
    return None if r is None else dict(zip(COLUMNS.split(", "), r, strict=True))


def _save(
    conn, quote_id: int, state: str, *, reference: str | None = None, attempts: int | None = None, error: str | None = None
):
    conn.execute(
        "UPDATE deliveries SET state=%s, reference=COALESCE(%s, reference), attempts=COALESCE(%s, attempts), "
        "last_error=%s, updated_at=now() WHERE quote_id=%s",
        (state, reference, attempts, error, quote_id),
    )


def _open(conn, quote_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The delivery row (made once, here) and the payload that was approved."""
    q = conn.execute("SELECT tender_id, total, draft_digest, status FROM quotes WHERE id=%s", (quote_id,)).fetchone()
    if q is None or q[3] != "approved" or not q[2]:
        raise ValueError("only an approved quote that records its draft digest can be delivered")
    tender_id, total, digest = q[0], round(float(q[1]), 2), q[2]
    key = f"tender-desk:{tender_id}:{quote_id}:{digest[:16]}"
    conn.execute(
        "INSERT INTO deliveries (quote_id, tender_id, idempotency_key) VALUES (%s,%s,%s) ON CONFLICT (quote_id) DO NOTHING",
        (quote_id, tender_id, key),
    )
    row = _row(conn, quote_id)
    if row is None:  # cannot happen: the insert above either made it or it already existed
        raise RuntimeError("delivery row missing after insert")
    return row, {"tender_id": tender_id, "quote_id": quote_id, "total": total, "draft_digest": digest}


def _settle(conn, row: dict[str, Any], payload: dict[str, Any], held: dict[str, Any]) -> dict[str, Any]:
    """Believe the other side's record only if it is exactly what was approved."""
    qid, tid = row["quote_id"], row["tender_id"]
    if round(float(held.get("total", -1)), 2) == payload["total"] and held.get("draft_digest") == payload["draft_digest"]:
        _save(conn, qid, "sent", reference=held["reference"])
        audit(conn, tid, "delivery_sent", reference=held["reference"], attempts=row["attempts"])
    else:
        _save(conn, qid, "conflict", error="the portal holds different content from what was approved")
        audit(conn, tid, "delivery_conflict", held_total=held.get("total"), approved_total=payload["total"])
    return _row(conn, qid)  # type: ignore[return-value]


def _send(conn, client: PortalClient, row: dict[str, Any], payload: dict[str, Any], max_attempts: int) -> dict[str, Any]:
    qid, tid, key = row["quote_id"], row["tender_id"], row["idempotency_key"]
    attempts = row["attempts"]
    for _ in range(max_attempts):
        attempts += 1
        _save(conn, qid, "pending", attempts=attempts)  # written BEFORE sending, so a crash leaves a trace to reconcile
        audit(conn, tid, "delivery_attempt", attempt=attempts)
        try:
            held = client.submit(key, payload)
        except DeliveryRejected as e:
            _save(conn, qid, "failed", error=str(e))
            audit(conn, tid, "delivery_failed", reason=str(e))
            return _row(conn, qid)  # type: ignore[return-value]
        except DeliveryAmbiguous as first:
            try:
                held_or_none = client.lookup(key)  # what does the other side say it holds?
            except (DeliveryAmbiguous, DeliveryRejected) as e:
                _save(conn, qid, "unknown", error=f"{first}; readback failed: {e}")
                audit(conn, tid, "delivery_unknown", sent=str(first), readback=str(e))
                return _row(conn, qid)  # type: ignore[return-value]
            if held_or_none is None:
                continue  # it provably did not arrive, so sending again (same key) is safe
            held = held_or_none
        row = {**row, "attempts": attempts}
        return _settle(conn, row, payload, held)
    _save(conn, qid, "failed", error=f"not received after {max_attempts} attempts (readback confirmed nothing held)")
    audit(conn, tid, "delivery_failed", reason="attempts exhausted")
    return _row(conn, qid)  # type: ignore[return-value]


def deliver(conn, client: PortalClient, quote_id: int, *, max_attempts: int = 3) -> dict[str, Any]:
    """Send an approved quote. Safe to call again for the same quote: it never sends a second booking."""
    row, payload = _open(conn, quote_id)
    if row["state"] in ("sent", "conflict"):
        return row
    if row["attempts"] > 0 and row["state"] in ("pending", "unknown"):
        return reconcile(conn, client, quote_id)  # something was already tried: readback first, never a blind resend
    return _send(conn, client, row, payload, max_attempts)


def reconcile(conn, client: PortalClient, quote_id: int, *, max_attempts: int = 3) -> dict[str, Any]:
    """Settle a delivery whose outcome is not known, by reading back what the other side holds."""
    row, payload = _open(conn, quote_id)
    if row["state"] in ("sent", "conflict"):
        return row
    if row["attempts"] == 0:  # never tried, so there is nothing to read back
        return _send(conn, client, row, payload, max_attempts)
    try:
        held = client.lookup(row["idempotency_key"])
    except (DeliveryAmbiguous, DeliveryRejected) as e:
        _save(conn, quote_id, "unknown", error=f"readback failed: {e}")
        return _row(conn, quote_id)  # type: ignore[return-value]
    if held is None:
        return _send(conn, client, row, payload, max_attempts)  # nothing held: now it is safe to send
    return _settle(conn, row, payload, held)
