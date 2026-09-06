"""The message bus agents talk over.

Every message is signed and the bus rejects anything unsigned or tampered with. That matters less
because an attacker might forge a message and more because it makes the run's transcript
tamper-evident: the memo a run produces can be checked against the messages that produced it, and
a modified transcript stops verifying.

Messages are append-only and ordered. An agent cannot rewrite what it said earlier, which is what
makes the Auditor's job possible.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class BusRejected(RuntimeError):
    """A message the bus will not carry."""


def _secret() -> bytes:
    """The signing key.

    A per-process random key is the right default: signatures are for integrity within a run, not
    for authenticating across machines, so a key that never leaves the process is both sufficient
    and impossible to leak.
    """
    configured = os.environ.get("AGENT_BUS_SECRET")
    if configured:
        return configured.encode()
    if not hasattr(_secret, "_generated"):
        _secret._generated = os.urandom(32)  # type: ignore[attr-defined]
    return _secret._generated  # type: ignore[attr-defined,return-value]


def sign(run_id: str, ordinal: int, sender: str, body: dict[str, Any]) -> str:
    payload = json.dumps(
        {"run_id": run_id, "ordinal": ordinal, "sender": sender, "body": body},
        sort_keys=True,
        default=str,
    )
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Message:
    run_id: str
    ordinal: int
    sender: str
    kind: str
    body: dict[str, Any]
    signature: str
    recipient: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def verify(self) -> bool:
        return hmac.compare_digest(
            self.signature, sign(self.run_id, self.ordinal, self.sender, self.body)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "sender": self.sender,
            "recipient": self.recipient,
            "kind": self.kind,
            "body": self.body,
            "created_at": self.created_at,
            "signature": self.signature[:16],
        }


class MessageBus:
    """Append-only, ordered, signed."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._messages: list[Message] = []

    def __len__(self) -> int:
        return len(self._messages)

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def publish(
        self, sender: str, kind: str, body: dict[str, Any], *, recipient: str | None = None
    ) -> Message:
        ordinal = len(self._messages)
        message = Message(
            run_id=self.run_id,
            ordinal=ordinal,
            sender=sender,
            kind=kind,
            body=body,
            recipient=recipient,
            signature=sign(self.run_id, ordinal, sender, body),
        )
        self._messages.append(message)
        return message

    def accept(self, message: Message) -> Message:
        """Take a message built elsewhere, refusing anything that does not verify."""
        if message.run_id != self.run_id:
            raise BusRejected("message belongs to a different run")
        if message.ordinal != len(self._messages):
            raise BusRejected(
                f"out of order: expected ordinal {len(self._messages)}, got {message.ordinal}"
            )
        if not message.verify():
            raise BusRejected("signature does not verify")
        self._messages.append(message)
        return message

    def verify_all(self) -> tuple[bool, list[int]]:
        """Whether the whole transcript still verifies, and which messages do not."""
        broken = [m.ordinal for m in self._messages if not m.verify()]
        return (not broken), broken

    def by_sender(self, sender: str) -> list[Message]:
        return [m for m in self._messages if m.sender == sender]

    def of_kind(self, kind: str) -> list[Message]:
        return [m for m in self._messages if m.kind == kind]

    def transcript(self) -> list[dict[str, Any]]:
        return [m.as_dict() for m in self._messages]
