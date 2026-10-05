"""Calls the gate tests make repeatedly: scan a pass, decide on it, or do both to let a party in."""


def scan(client, event_id: int, token: str, gate: str | None = "Gate 1"):
    body = {"token": token} if gate is None else {"token": token, "gate": gate}
    return client.post(f"/api/v1/gate/events/{event_id}/scan", json=body)


def decide(client, event_id: int, token: str, decision: str = "approve", gate: str | None = "Gate 1", **fields):
    body = {"token": token, "decision": decision, **fields}
    if gate is not None:
        body["gate"] = gate
    return client.post(f"/api/v1/gate/events/{event_id}/decision", json=body)


def guest_ids(client, event_id: int, token: str) -> list[int]:
    """Accompanying guests on the pass, in registration order, as the scanner lists them."""
    return [member["id"] for member in scan(client, event_id, token).json()["guest"]["members"]]


def admit(client, event_id: int, token: str, *, guests: int = 0, gate: str | None = "Gate 1"):
    """Scan the pass, then approve it with the employee's ID checked and the first `guests` guests present."""
    ids = guest_ids(client, event_id, token)[:guests]
    return decide(client, event_id, token, gate=gate, employee_id_checked=True, guest_ids_entered=ids)


def admit_everyone(client, event_id: int, token: str, gate: str | None = "Gate 1"):
    ids = guest_ids(client, event_id, token)
    return decide(client, event_id, token, gate=gate, employee_id_checked=True, guest_ids_entered=ids)
