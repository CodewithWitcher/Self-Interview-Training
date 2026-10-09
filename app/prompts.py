"""Reply schemas and prompt builders (PS 2 to 5)."""

from pydantic import BaseModel


class Ping(BaseModel):
    ok: bool


PING_SYSTEM = "Reply with JSON."
PING_USER = 'Set "ok" to true.'
