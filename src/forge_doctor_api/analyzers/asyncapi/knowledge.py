"""Bundled AsyncAPI knowledge pack (§20, §128).

AsyncAPI 2.x uses channel `publish`/`subscribe` verbs; 3.x uses operations
with `action: send|receive`. Both normalize into one `AsyncApiModel` —
`send` means the application produces onto the channel, `receive` means it
consumes from it.
"""

from __future__ import annotations

import re

KNOWLEDGE_PACK_VERSION = "2026.09"

SUPPORTED_FAMILIES: tuple[str, ...] = (
    "2.0", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6",
    "3.0", "3.1",
)

KNOWN_RELEASES: tuple[str, ...] = (
    "2.0.0", "2.1.0", "2.2.0", "2.3.0", "2.4.0", "2.5.0", "2.6.0",
    "3.0.0", "3.1.0",
)

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
)

# Broker protocols this pack recognizes as binding evidence.
KNOWN_BINDINGS: tuple[str, ...] = (
    "amqp", "amqp1", "anypointmq", "googlepubsub", "http", "ibmmq",
    "jms", "kafka", "mercure", "mqtt", "mqtt5", "nats", "pulsar",
    "redis", "sns", "solace", "sqs", "stomp", "ws",
)


def version_family(version: str) -> str | None:
    match = VERSION_PATTERN.match(version)
    if match is None:
        return None
    family = f"{match['major']}.{match['minor']}"
    return family if family in SUPPORTED_FAMILIES else None
