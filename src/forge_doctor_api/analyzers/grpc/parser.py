"""Hand-rolled .proto parser — stdlib only, deterministic, offline (§25).

Strong marker: `.proto` extension. Comment-stripped source is scanned
line-wise; a brace stack tracks message/enum/service/oneof context.
Comment-embedded fake services never reach the grammar (§100). Unresolved
and external imports are recorded, never fetched (§1).
"""

from __future__ import annotations

import re
from pathlib import Path

from forge_doctor_api.analyzers.grpc.model import (
    GrpcProjectModel,
    ProtoDocument,
    ProtoDocumentStatus,
    ProtoEnum,
    ProtoField,
    ProtoFile,
    ProtoIssue,
    ProtoIssueCode,
    ProtoMessage,
    ProtoMethod,
    ProtoService,
    StreamingMode,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation

_SYNTAX = re.compile(r'^\s*syntax\s*=\s*"(proto[23])"\s*;?$')
_PACKAGE = re.compile(r"^\s*package\s+([a-zA-Z][\w.]*)\s*;?$")
_IMPORT = re.compile(r'^\s*import\s+(?:public|weak\s+)?"([^"]+)"\s*;?$')
_MESSAGE = re.compile(r"^\s*message\s+([A-Z]\w*)\s*\{?")
_ENUM = re.compile(r"^\s*enum\s+([A-Z]\w*)\s*\{?")
_SERVICE = re.compile(r"^\s*service\s+([A-Z]\w*)\s*\{?")
_ONEOF = re.compile(r"^\s*oneof\s+(\w+)\s*\{?")
_RPC = re.compile(
    r"^\s*rpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*"
    r"\(\s*(stream\s+)?([\w.]+)\s*\)"
)
_FIELD = re.compile(
    r"^\s*(optional|required|repeated)?\s*([\w.]+)\s+(\w+)\s*=\s*(\d+)"
)
_MAP_FIELD = re.compile(r"^\s*map\s*<([\w.]+)\s*,\s*([\w.]+)>\s+(\w+)\s*=\s*(\d+)")
_ENUM_VALUE = re.compile(r"^\s*([A-Z_][\w]*)\s*=\s*(-?\d+)")
_RESERVED = re.compile(r"^\s*reserved\s+(.+?)\s*;?$")
_RESERVED_RANGE = re.compile(r"(\d+)\s+(?:to|-)\s+(\d+)")
_RESERVED_NAME = re.compile(r'"(\w+)"')
_IDEMPOTENT = re.compile(r"idempotency_level\s*=\s*(IDEMPOTENT|NO_SIDE_EFFECTS)")


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Physical text -> (lineno, logical line) pairs.

    Comments are stripped, then `{` and `}` split lines so single-line
    blocks (`enum E { A = 0; }`) parse like multi-line ones while keeping
    real line numbers.
    """
    out: list[tuple[int, str]] = []
    for lineno, physical in enumerate(_strip_comments(text), start=1):
        for piece in re.split(r"([{};])", physical):
            piece = piece.strip()
            if piece and piece != ";":
                out.append((lineno, piece))
    return out


def _strip_comments(text: str) -> list[str]:
    """Remove // and /* */ comments while preserving line count."""
    lines = text.split("\n")
    out: list[str] = []
    in_block = False
    for line in lines:
        buf = ""
        i = 0
        in_str = False
        while i < len(line):
            ch = line[i]
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    i = len(line)
                    continue
                in_block = False
                i = end + 2
                continue
            if in_str:
                buf += ch
                if ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                buf += ch
                i += 1
                continue
            if line.startswith("//", i):
                break
            if line.startswith("/*", i):
                in_block = True
                i += 2
                continue
            buf += ch
            i += 1
        out.append(buf)
    return out


def _reserved_numbers(spec: str) -> tuple[int, ...]:
    nums: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        rng = _RESERVED_RANGE.search(part)
        if rng:
            a, b = int(rng.group(1)), int(rng.group(2))
            nums.update(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            nums.add(int(part))
    return tuple(sorted(nums))


def _reserved_names(spec: str) -> tuple[str, ...]:
    return tuple(sorted(_RESERVED_NAME.findall(spec)))


def _streaming(client_stream: str | None, server_stream: str | None) -> StreamingMode:
    if client_stream and server_stream:
        return StreamingMode.BIDI_STREAMING
    if client_stream:
        return StreamingMode.CLIENT_STREAMING
    if server_stream:
        return StreamingMode.SERVER_STREAMING
    return StreamingMode.UNARY


def _parse_proto(path: str, lines: list[tuple[int, str]]) -> tuple[
    ProtoFile | None,
    list[ProtoService],
    list[ProtoMessage],
    list[ProtoEnum],
    list[ProtoIssue],
]:
    issues: list[ProtoIssue] = []
    services: list[ProtoService] = []
    messages: list[ProtoMessage] = []
    enums: list[ProtoEnum] = []

    syntax = "proto2"
    package = ""
    imports: list[str] = []
    loc = SourceLocation(path=path, line=1)

    # context stack: ("message", name) | ("enum", name) | ("service", name) | ("oneof", name)
    ctx: list[tuple[str, str]] = []
    fields: list[ProtoField] = []
    reserved_nums: list[int] = []
    reserved_nms: list[str] = []
    oneofs: list[str] = []
    methods: list[ProtoMethod] = []
    enum_values: dict[str, int] = {}
    pending_idem: list[str] = []
    pending_brace = False  # an opener consumed a `;`-split `{` already

    def close_block(parent_name: str) -> None:
        nonlocal fields, reserved_nums, reserved_nms, oneofs, methods, enum_values
        if not ctx:
            return
        kind, bname = ctx.pop()
        if kind == "message":
            messages.append(
                ProtoMessage(
                    name=parent_name + "." + bname if parent_name else bname,
                    fields=tuple(fields),
                    reserved_numbers=tuple(sorted(set(reserved_nums))),
                    reserved_names=tuple(sorted(set(reserved_nms))),
                    oneofs=tuple(sorted(set(oneofs))),
                    location=loc,
                )
            )
            fields, reserved_nums, reserved_nms, oneofs = [], [], [], []
        elif kind == "enum":
            enums.append(
                ProtoEnum(
                    name=parent_name + "." + bname if parent_name else bname,
                    values=dict(enum_values),
                    location=loc,
                )
            )
            enum_values = {}
        elif kind == "service":
            services.append(
                ProtoService(
                    name=bname,
                    package=package,
                    methods=tuple(methods),
                    location=loc,
                )
            )
            methods = []
        elif kind == "oneof":
            pass

    def innermost() -> str | None:
        for kind, _ in reversed(ctx):
            if kind != "block":
                return kind
        return None

    for lineno, line in lines:
        if m := _SYNTAX.match(line):
            syntax = m.group(1)
            continue
        if m := _PACKAGE.match(line):
            package = m.group(1)
            continue
        if m := _IMPORT.match(line):
            imports.append(m.group(1))
            continue
        if m := _MESSAGE.match(line):
            ctx.append(("message", m.group(1)))
            pending_brace = True
            continue
        if m := _ENUM.match(line):
            ctx.append(("enum", m.group(1)))
            enum_values = {}
            pending_brace = True
            continue
        if m := _SERVICE.match(line):
            ctx.append(("service", m.group(1)))
            methods = []
            pending_brace = True
            continue
        if m := _ONEOF.match(line):
            ctx.append(("oneof", m.group(1)))
            if ctx[-2:-1] and ctx[-2][0] == "message":
                oneofs.append(m.group(1))
            pending_brace = True
            continue
        if line == "{":
            if pending_brace:
                pending_brace = False
            else:
                ctx.append(("block", ""))  # rpc/option bodies: transparent ctx
            continue
        if line.startswith("}"):
            parent_name = ".".join(n for k, n in ctx[:-1] if k == "message")
            close_block(parent_name)
            continue
        scope = innermost()
        if scope == "service":
            if im := _IDEMPOTENT.search(line):
                if methods:
                    last = methods[-1]
                    methods[-1] = ProtoMethod(
                        name=last.name,
                        request_type=last.request_type,
                        response_type=last.response_type,
                        streaming=last.streaming,
                        idempotent_evidence=(
                            *last.idempotent_evidence, im.group(1)
                        ),
                        location=last.location,
                    )
                else:
                    pending_idem.append(im.group(1))
                continue
            if m := _RPC.match(line):
                methods.append(
                    ProtoMethod(
                        name=m.group(1),
                        request_type=m.group(3).lstrip("."),
                        response_type=m.group(5).lstrip("."),
                        streaming=_streaming(m.group(2), m.group(4)),
                        idempotent_evidence=tuple(pending_idem),
                        location=SourceLocation(path=path, line=lineno),
                    )
                )
                pending_idem = []
                continue
        if scope == "enum" and (m := _ENUM_VALUE.match(line)):
            enum_values[m.group(1)] = int(m.group(2))
            continue
        if ctx and ctx[-1][0] == "enum" and (m := _ENUM_VALUE.match(line)):
            enum_values[m.group(1)] = int(m.group(2))
            continue
        if scope in {"message", "oneof"}:
            if m := _RESERVED.match(line):
                reserved_nums.extend(_reserved_numbers(m.group(1)))
                reserved_nms.extend(_reserved_names(m.group(1)))
                continue
            if m := _MAP_FIELD.match(line):
                fields.append(
                    ProtoField(
                        name=m.group(3),
                        type=f"map<{m.group(1)},{m.group(2)}>",
                        number=int(m.group(4)),
                        label="map",
                        oneof=ctx[-1][1] if ctx[-1][0] == "oneof" else None,
                        location=SourceLocation(path=path, line=lineno),
                    )
                )
                continue
            if m := _FIELD.match(line):
                fields.append(
                    ProtoField(
                        name=m.group(3),
                        type=m.group(2),
                        number=int(m.group(4)),
                        label=m.group(1),
                        oneof=ctx[-1][1] if ctx[-1][0] == "oneof" else None,
                        location=SourceLocation(path=path, line=lineno),
                    )
                )
                continue

    if ctx:
        issues.append(
            ProtoIssue(
                code=ProtoIssueCode.MALFORMED,
                message=f"unclosed {ctx[-1][0]} {ctx[-1][1]!r}",
                location=loc,
            )
        )
        return None, services, messages, enums, issues

    pf = ProtoFile(
        path=path,
        syntax=syntax,
        package=package,
        imports=tuple(imports),
        location=loc,
    )
    return pf, services, messages, enums, issues


def load_grpc_project(
    context: ProjectContext, files: list[str]
) -> GrpcProjectModel:
    documents: list[ProtoDocument] = []
    protos: list[ProtoFile] = []
    services: list[ProtoService] = []
    messages: list[ProtoMessage] = []
    enums: list[ProtoEnum] = []
    issues: list[ProtoIssue] = []
    known = {Path(f).as_posix() for f in files if f.endswith(".proto")}
    basenames = {Path(f).name for f in files if f.endswith(".proto")}

    for path in sorted(files):
        if not path.endswith(".proto"):
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        pf, svcs, msgs, enms, errs = _parse_proto(path, _logical_lines(text))
        issues.extend(errs)
        if pf is None:
            documents.append(
                ProtoDocument(path=path, status=ProtoDocumentStatus.MALFORMED)
            )
            continue
        unresolved = []
        for imp in pf.imports:
            base = Path(imp).name
            if Path(imp).as_posix() not in known and base not in basenames:
                unresolved.append(imp)
                issues.append(
                    ProtoIssue(
                        code=ProtoIssueCode.UNRESOLVED_IMPORT,
                        message=f"import {imp!r} not found locally (external)",
                        location=SourceLocation(path=path),
                    )
                )
        pf = ProtoFile(
            path=pf.path,
            syntax=pf.syntax,
            package=pf.package,
            imports=pf.imports,
            unresolved_imports=tuple(sorted(unresolved)),
            location=pf.location,
        )
        protos.append(pf)
        services.extend(svcs)
        messages.extend(msgs)
        enums.extend(enms)
        documents.append(
            ProtoDocument(path=path, status=ProtoDocumentStatus.PARSED)
        )

    from forge_doctor_api.analyzers.grpc.reliability import (
        extract_service_configs,
        extract_stub_calls,
    )

    return GrpcProjectModel(
        documents=tuple(documents),
        files=tuple(protos),
        services=tuple(services),
        messages=tuple(messages),
        enums=tuple(enums),
        service_configs=extract_service_configs(context, files),
        client_calls=extract_stub_calls(context, files),
        issues=tuple(issues),
    )
