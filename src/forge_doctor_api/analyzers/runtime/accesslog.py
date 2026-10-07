"""NGINX/Envoy access-log adapter (§30) -> RequestSummary records.

Strong marker: `%REQ(` Envoy directives or an nginx `log_format`-shaped
line (`$status`, `$request`, `$request_time`, `$http_x_request_id`).
Comment lines and free text never attribute (§100).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import BinaryIO

from forge_doctor_api.analyzers.runtime.adapter import RuntimeArtifactAdapter
from forge_doctor_api.analyzers.runtime.model import RequestSummary
from forge_doctor_api.core.models import Evidence, EvidenceKind

# nginx combined: $remote_addr - - [$time_local] "$request" $status
#   $body_bytes_sent "$http_referer" "$http_user_agent"
_NGINX = re.compile(
    r'^\S+ \S+ \S+ \[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
    r"(?P<status>\d{3}) (?P<bytes>\d+)"
)
# envoy default-ish: [%START_TIME%] "METHOD path PROTO" STATUS ...
_ENVOY = re.compile(
    r'^\[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>\S+) [^"]*" (?P<status>\d{3})'
)
_REQID = re.compile(
    r'(?i)\b(x-request-id|x-correlation-id|request_id|traceparent)\b[:=]\s*"?([\w-]+)'
)


class AccessLogAdapter(RuntimeArtifactAdapter):
    name = "access-log"

    def detect(self, path: str, head: bytes) -> bool:
        text = head.decode("utf-8", errors="replace")
        return any(
            _NGINX.match(line) or _ENVOY.match(line)
            for line in text.splitlines()[:5]
        )

    def iter_summaries(
        self, reader: BinaryIO, path: str
    ) -> Iterator[RequestSummary]:
        for lineno, raw in enumerate(reader, start=1):
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            m = _NGINX.match(line) or _ENVOY.match(line)
            if not m:
                continue
            rid = _REQID.search(line)
            yield RequestSummary(
                method=m.group("method"),
                path=m.group("path"),
                status=int(m.group("status")),
                request_id=rid.group(2) if rid else None,
                bytes_sent=(
                    int(m.group("bytes")) if "bytes" in m.re.groupindex else None
                ),
                evidence=(
                    Evidence(
                        kind=EvidenceKind.RUNTIME,
                        source=path,
                        summary=f"access log line {lineno}",
                        line=lineno,
                    ),
                ),
            )
