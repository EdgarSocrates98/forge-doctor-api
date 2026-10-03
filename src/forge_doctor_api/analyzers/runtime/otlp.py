"""OTLP JSON trace-export adapter (§86, §171, §173).

Streams `resourceSpans[].scopeSpans[].spans[]` objects out of a large
single-document export without loading it fully: a chunk-fed scanner
locates `spans` arrays and extracts balanced `{...}` span objects one at
a time. The enclosing `service.name` resource attribute (seen earlier in
stream order) is attached to each span. Raw span bodies are parsed then
discarded — summaries only, per §173.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, BinaryIO

from forge_doctor_api.analyzers.runtime.adapter import RuntimeArtifactAdapter
from forge_doctor_api.analyzers.runtime.model import Span, SpanKind, SpanStatus
from forge_doctor_api.core.models import Evidence, EvidenceKind
from forge_doctor_api.core.redaction import redact_text

_CHUNK = 1 << 16
_SPANS_KEY = '"spans"'
_SVC_VALUE = re.compile(r'"stringValue"\s*:\s*"([^"]*)"')

_KIND_MAP = {
    1: SpanKind.INTERNAL,
    2: SpanKind.SERVER,
    3: SpanKind.CLIENT,
    4: SpanKind.PRODUCER,
    5: SpanKind.CONSUMER,
}
_STATUS_MAP = {0: SpanStatus.UNSET, 1: SpanStatus.OK, 2: SpanStatus.ERROR}


class OtlpJsonAdapter(RuntimeArtifactAdapter):
    name = "otlp-json"

    def detect(self, path: str, head: bytes) -> bool:
        return b'"resourceSpans"' in head and b'"spans"' in head

    def iter_spans(self, reader: BinaryIO, path: str) -> Iterator[Span]:
        for service, raw, offset in _iter_span_objects(reader):
            span = _to_span(service, raw, path, offset)
            if span is not None:
                yield span


def _iter_span_objects(
    reader: BinaryIO,
) -> Iterator[tuple[str | None, str, int]]:
    """Yield (service_name, span_json_text, char_offset) per span object.

    Chunk-fed scan: find `"spans"` arrays, then split balanced objects.
    A rolling tail keeps the last-seen service.name value; `base` tracks
    consumed characters so yielded offsets are absolute in the decoded
    stream.
    """
    buf = ""
    i = 0
    base = 0
    collecting = False
    depth = 0
    obj_start = -1
    in_str = False
    esc = False
    service: str | None = None

    while True:
        if i >= len(buf):
            chunk = reader.read(_CHUNK)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            continue

        ch = buf[i]
        if not collecting:
            if not in_str:
                if buf.startswith('"service.name"', i):
                    m = _SVC_VALUE.search(buf, i + 14, i + 400)
                    if m:
                        service = m.group(1)
                    i += 14
                    continue
                if buf.startswith(_SPANS_KEY, i):
                    j = i + len(_SPANS_KEY)
                    while j < len(buf) and buf[j] in " \t\n:":
                        j += 1
                    if j >= len(buf):  # need more data to confirm `[`
                        i = len(buf)
                        continue
                    if buf[j] == "[":
                        collecting = True
                        depth = 1
                        i = j + 1
                        continue
                    i = j + 1
                    continue
                if ch == '"':
                    in_str = True
            else:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            i += 1
        else:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 1:
                    obj_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 1 and obj_start >= 0:
                    yield service, buf[obj_start : i + 1], base + obj_start
                    obj_start = -1
            elif ch == "[" and depth >= 1:
                depth += 1
            elif ch == "]" and depth > 1:
                depth -= 1
            elif ch == "]" and depth == 1:
                collecting = False
            i += 1

        # bound memory: drop consumed prefix when safe
        if i > _CHUNK * 2:
            if collecting and obj_start >= 0:
                buf = buf[obj_start:]
                base += obj_start
                i -= obj_start
                obj_start = 0
            else:
                buf = buf[i - 512 :]
                base += i - 512
                i = 512


def _attr_map(attrs: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(attrs, list):
        return out
    for a in attrs:
        if not isinstance(a, dict):
            continue
        key = a.get("key")
        val = a.get("value", {})
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        sval: str | None = None
        for vk in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if vk in val:
                sval = str(val[vk])
                break
        if sval is not None:
            out[key] = redact_text(sval)
    return out


def _to_span(
    service: str | None, raw: str, path: str, offset: int
) -> Span | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    attrs = _attr_map(data.get("attributes"))
    start = int(data.get("startTimeUnixNano") or 0)
    end = int(data.get("endTimeUnixNano") or 0)
    status = data.get("status") or {}
    rpc = attrs.get("rpc.service") or ""
    if attrs.get("rpc.method"):
        rpc = f"{rpc}/{attrs['rpc.method']}" if rpc else attrs["rpc.method"]
    operation = attrs.get("http.route") or rpc or data.get("name") or "(unnamed)"
    svc = service or attrs.get("service.name") or "(unknown)"
    return Span(
        service=str(svc),
        operation=str(operation),
        parent_id=data.get("parentSpanId") or None,
        span_id=data.get("spanId") or None,
        trace_id=data.get("traceId") or None,
        duration_ms=(end - start) / 1e6 if end >= start and end else None,
        status=_STATUS_MAP.get(status.get("code", 0), SpanStatus.UNSET),
        kind=_KIND_MAP.get(data.get("kind", 1), SpanKind.INTERNAL),
        attributes=attrs,
        evidence=(
            Evidence(
                kind=EvidenceKind.RUNTIME,
                source=path,
                summary=f"span {data.get('spanId', '?')}",
                offset=offset,
            ),
        ),
    )
