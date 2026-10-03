"""AsyncAPI 2.x/3.x -> `AsyncApiModel` (§20, spec 011).

Strong-marker gate: the `asyncapi:` version key is required — `channels:`
alone is insufficient (§101). Never raises; never fetches external refs.
Local `#/...` refs resolve within the same document; external refs are
recorded, not followed (§1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from forge_doctor_api.analyzers.asyncapi.knowledge import (
    SUPPORTED_FAMILIES,
    VERSION_PATTERN,
    version_family,
)
from forge_doctor_api.analyzers.asyncapi.model import (
    AsyncAction,
    AsyncApiChannel,
    AsyncApiDocument,
    AsyncApiIssue,
    AsyncApiMessage,
    AsyncApiOperation,
    AsyncApiProjectModel,
    AsyncApiSchema,
    AsyncApiSecurityRequirement,
    AsyncApiServer,
    AsyncDocumentStatus,
    AsyncIssueCode,
)
from forge_doctor_api.analyzers.openapi.loader import escape_pointer_token, load_document
from forge_doctor_api.analyzers.openapi.shape import schema_shape
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation

_DISCOVERY_SUFFIXES = (".yaml", ".yml", ".json")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", "site-packages"}


@dataclass
class _Doc:
    path: str
    status: AsyncDocumentStatus
    value: Any = None
    locations: dict[str, tuple[int, int]] = field(default_factory=dict)
    version: str | None = None
    family: str | None = None


def _detect(value: Any) -> tuple[AsyncDocumentStatus, str | None, str | None]:
    if not isinstance(value, dict):
        return AsyncDocumentStatus.NOT_ASYNCAPI, None, None
    raw = value.get("asyncapi")
    if raw is None:
        return AsyncDocumentStatus.NOT_ASYNCAPI, None, None
    if not isinstance(raw, str) or not VERSION_PATTERN.match(raw):
        return AsyncDocumentStatus.INVALID_VERSION, raw if isinstance(raw, str) else None, None
    family = version_family(raw)
    if family is None:
        return AsyncDocumentStatus.UNSUPPORTED_VERSION, raw, None
    return AsyncDocumentStatus.PARSED, raw, family


class _Builder:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.docs: dict[str, _Doc] = {}
        self.issues: list[AsyncApiIssue] = []
        self.out: dict[str, list[object]] = {}

    def loc(self, path: str, pointer: str = "") -> SourceLocation:
        doc = self.docs.get(path)
        locations = doc.locations if doc else {}
        probe = pointer
        while True:
            if probe in locations:
                line, column = locations[probe]
                return SourceLocation(path=path, line=line, column=column)
            if not probe:
                return SourceLocation(path=path)
            probe = probe.rsplit("/", 1)[0]

    def issue(
        self, code: AsyncIssueCode, message: str, path: str, pointer: str = ""
    ) -> None:
        self.issues.append(
            AsyncApiIssue(code=code, message=message, location=self.loc(path, pointer))
        )

    def add(self, bucket: str, item: object) -> None:
        self.out.setdefault(bucket, []).append(item)

    # -- loading ------------------------------------------------------------

    def load(self, path: str, explicit: bool) -> _Doc | None:
        if path in self.docs:
            return self.docs[path]
        try:
            text = self.context.read_text(path)
        except Exception:
            doc = _Doc(path, AsyncDocumentStatus.UNREADABLE)
            self.docs[path] = doc
            self.issue(AsyncIssueCode.UNREADABLE, f"cannot read {path}", path)
            return doc
        loaded = load_document(text, "json" if path.endswith(".json") else "yaml")
        if not loaded.ok:
            if not explicit and '"asyncapi"' not in text and "'asyncapi'" not in text \
                    and "asyncapi:" not in text:
                return None
            doc = _Doc(path, AsyncDocumentStatus.MALFORMED)
            self.docs[path] = doc
            self.issue(AsyncIssueCode.MALFORMED, f"cannot parse {path}", path)
            return doc
        status, version, family = _detect(loaded.value)
        if status is AsyncDocumentStatus.NOT_ASYNCAPI and not explicit:
            return None
        doc = _Doc(path, status, loaded.value, loaded.locations, version, family)
        self.docs[path] = doc
        if status is AsyncDocumentStatus.NOT_ASYNCAPI:
            self.issue(AsyncIssueCode.NOT_ASYNCAPI, "missing root 'asyncapi' marker", path)
        elif status is AsyncDocumentStatus.INVALID_VERSION:
            self.issue(
                AsyncIssueCode.INVALID_VERSION,
                f"'asyncapi' must be a MAJOR.MINOR.PATCH string, got {version!r}",
                path,
            )
        elif status is AsyncDocumentStatus.UNSUPPORTED_VERSION:
            self.issue(
                AsyncIssueCode.UNSUPPORTED_VERSION,
                f"unsupported AsyncAPI version {version!r} "
                f"(supported: {', '.join(f'{f}.x' for f in SUPPORTED_FAMILIES)})",
                path,
            )
        return doc

    # -- per-document walk ----------------------------------------------------

    def _ref_name(self, value: Any) -> str | None:
        """Return the target name for a local `$ref` string; None if external."""
        if isinstance(value, dict) and isinstance(value.get("$ref"), str):
            ref = value["$ref"]
            return str(ref.rsplit("/", 1)[-1]) if ref.startswith("#/") else str(ref)
        return None

    def _message(
        self, path: str, pointer: str, node: Any, doc: _Doc, default_name: str | None = None
    ) -> None:
        """Emit an `AsyncApiMessage` for one message node."""
        if not isinstance(node, dict):
            return
        name: str | None = default_name
        target = node
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("#/"):
                name = str(ref.rsplit("/", 1)[-1])
                resolved = self._lookup(doc, ref)
                if resolved is not None:
                    target = resolved
                else:
                    self.issue(
                        AsyncIssueCode.MISSING_REF_TARGET,
                        f"unresolved message ref {ref}",
                        path,
                        pointer,
                    )
            else:
                name = str(ref.rsplit("/", 1)[-1])
                self.issue(
                    AsyncIssueCode.INVALID_REF, f"external ref not fetched: {ref}", path, pointer
                )
        payload = target.get("payload") if isinstance(target, dict) else None
        payload_ref = self._ref_name(payload)
        corr = target.get("correlationId") if isinstance(target, dict) else None
        corr_loc = corr.get("location") if isinstance(corr, dict) else None
        bindings = self._binding_names(target.get("bindings") if isinstance(target, dict) else None)
        if name is None and isinstance(target, dict) and isinstance(target.get("name"), str):
            name = target["name"]
        msg = AsyncApiMessage(
            location=self.loc(path, pointer),
            pointer=pointer,
            name=name if isinstance(name, str) else None,
            correlation_id_location=corr_loc if isinstance(corr_loc, str) else None,
            payload_ref=payload_ref,
            payload_shape=schema_shape(payload),
            payload_content=payload if isinstance(payload, dict) else None,
            content_type=(
                target.get("contentType") if isinstance(target.get("contentType"), str) else None
            ),
            bindings=bindings,
        )
        self.add("messages", msg)

    @staticmethod
    def _binding_names(bindings: Any) -> tuple[str, ...]:
        if not isinstance(bindings, dict):
            return ()
        return tuple(sorted(str(k) for k in bindings if not str(k).startswith("x-")))

    @staticmethod
    def _markers(node: Any) -> tuple[str, ...]:
        """x-* keys on `node` plus every nested key inside `bindings` — the
        surface checks use to look for retry/DLQ/ordering evidence."""
        if not isinstance(node, dict):
            return ()
        found = {str(k) for k in node if str(k).startswith("x-")}
        bindings = node.get("bindings")
        if isinstance(bindings, dict):
            stack = [bindings]
            while stack:
                current = stack.pop()
                for key, value in current.items():
                    found.add(str(key))
                    if isinstance(value, dict):
                        stack.append(value)
                    elif isinstance(value, list):
                        stack.extend(v for v in value if isinstance(v, dict))
        return tuple(sorted(found))

    def _lookup(self, doc: _Doc, ref: str) -> Any:
        """Resolve a local `#/a/b/c` pointer inside `doc.value`."""
        if not isinstance(doc.value, dict) or not ref.startswith("#/"):
            return None
        node: Any = doc.value
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                return None
            node = node[token]
        return node

    def _channels_2x(self, doc: _Doc) -> None:
        channels = doc.value.get("channels")
        if not isinstance(channels, dict):
            return
        for address in sorted(channels):
            node = channels[address]
            if not isinstance(node, dict):
                continue
            cptr = f"/channels/{escape_pointer_token(address)}"
            params = node.get("parameters")
            message_ptrs: list[str] = []
            op_index = 0
            for verb, action in (("publish", AsyncAction.SEND), ("subscribe", AsyncAction.RECEIVE)):
                op = node.get(verb)
                if not isinstance(op, dict):
                    continue
                optr = f"{cptr}/{verb}"
                message = op.get("message")
                msg_ptrs: list[str] = []
                if isinstance(message, dict):
                    if isinstance(message.get("oneOf"), list):
                        for i, alt in enumerate(message["oneOf"]):
                            mptr = f"{optr}/message/oneOf/{i}"
                            self._message(doc.path, mptr, alt, doc)
                            msg_ptrs.append(mptr)
                    else:
                        mptr = f"{optr}/message"
                        self._message(doc.path, mptr, message, doc)
                        msg_ptrs.append(mptr)
                message_ptrs.extend(msg_ptrs)
                self.add(
                    "operations",
                    AsyncApiOperation(
                        location=self.loc(doc.path, optr),
                        pointer=optr,
                        name=op.get("operationId", f"{verb}:{address}"),
                        action=action,
                        channel_pointer=cptr,
                        message_pointers=tuple(msg_ptrs),
                        bindings=self._binding_names(op.get("bindings")),
                        markers=self._markers(op),
                    ),
                )
                op_index += 1
            self.add(
                "channels",
                AsyncApiChannel(
                    location=self.loc(doc.path, cptr),
                    pointer=cptr,
                    name=address,
                    address=address,
                    parameters=(
                        tuple(sorted(str(k) for k in params))
                        if isinstance(params, dict)
                        else ()
                    ),
                    message_pointers=tuple(message_ptrs),
                    bindings=self._binding_names(node.get("bindings")),
                    markers=self._markers(node),
                ),
            )

    def _channels_3x(self, doc: _Doc) -> None:
        channels = doc.value.get("channels")
        if not isinstance(channels, dict):
            channels = {}
        for name in sorted(channels):
            node = channels[name]
            if not isinstance(node, dict):
                continue
            cptr = f"/channels/{escape_pointer_token(name)}"
            messages = node.get("messages")
            msg_ptrs: list[str] = []
            if isinstance(messages, dict):
                for mname in sorted(messages):
                    mptr = f"{cptr}/messages/{escape_pointer_token(mname)}"
                    self._message(doc.path, mptr, messages[mname], doc)
                    msg_ptrs.append(mptr)
            params = node.get("parameters")
            self.add(
                "channels",
                AsyncApiChannel(
                    location=self.loc(doc.path, cptr),
                    pointer=cptr,
                    name=name,
                    address=node.get("address") if isinstance(node.get("address"), str) else None,
                    parameters=(
                        tuple(sorted(str(k) for k in params))
                        if isinstance(params, dict)
                        else ()
                    ),
                    message_pointers=tuple(msg_ptrs),
                    bindings=self._binding_names(node.get("bindings")),
                    markers=self._markers(node),
                ),
            )
        operations = doc.value.get("operations")
        if not isinstance(operations, dict):
            return
        for name in sorted(operations):
            op = operations[name]
            if not isinstance(op, dict):
                continue
            optr = f"/operations/{escape_pointer_token(name)}"
            raw_action = op.get("action")
            action = (
                AsyncAction.SEND
                if raw_action == "send"
                else AsyncAction.RECEIVE if raw_action == "receive" else None
            )
            if action is None:
                self.issue(
                    AsyncIssueCode.INVALID_REF,
                    f"operation {name} has unknown action {raw_action!r}",
                    doc.path,
                    optr,
                )
                continue
            channel_ptr: str | None = None
            channel = op.get("channel")
            if isinstance(channel, dict) and isinstance(channel.get("$ref"), str):
                ref = channel["$ref"]
                if ref.startswith("#/channels/"):
                    channel_ptr = "/channels/" + ref[len("#/channels/"):]
                else:
                    self.issue(
                        AsyncIssueCode.INVALID_REF,
                        f"operation {name} channel ref not local: {ref}",
                        doc.path,
                        optr,
                    )
            op_msg_ptrs: list[str] = []
            msgs = op.get("messages")
            if isinstance(msgs, list):
                for i, msg in enumerate(msgs):
                    mptr = f"{optr}/messages/{i}"
                    self._message(doc.path, mptr, msg, doc)
                    op_msg_ptrs.append(mptr)
            self.add(
                "operations",
                AsyncApiOperation(
                    location=self.loc(doc.path, optr),
                    pointer=optr,
                    name=name,
                    action=action,
                    channel_pointer=channel_ptr,
                    message_pointers=tuple(op_msg_ptrs),
                    bindings=self._binding_names(op.get("bindings")),
                    markers=self._markers(op),
                ),
            )

    def _components(self, doc: _Doc) -> None:
        comps = doc.value.get("components")
        if not isinstance(comps, dict):
            return
        schemas = comps.get("schemas")
        if isinstance(schemas, dict):
            for name in sorted(schemas):
                sptr = f"/components/schemas/{escape_pointer_token(name)}"
                self.add(
                    "schemas",
                    AsyncApiSchema(
                        location=self.loc(doc.path, sptr),
                        pointer=sptr,
                        name=name,
                        content=schemas[name],
                    ),
                )
        messages = comps.get("messages")
        if isinstance(messages, dict):
            for name in sorted(messages):
                mptr = f"/components/messages/{escape_pointer_token(name)}"
                self._message(doc.path, mptr, messages[name], doc, default_name=name)
        security = comps.get("securitySchemes")
        if isinstance(security, dict):
            for name in sorted(security):
                sptr = f"/components/securitySchemes/{escape_pointer_token(name)}"
                self.add(
                    "security_requirements",
                    AsyncApiSecurityRequirement(
                        location=self.loc(doc.path, sptr),
                        pointer=sptr,
                        owner_pointer="",
                        scheme=name,
                    ),
                )

    def _servers(self, doc: _Doc) -> None:
        servers = doc.value.get("servers")
        if not isinstance(servers, dict):
            return
        for name in sorted(servers):
            node = servers[name]
            if not isinstance(node, dict):
                continue
            sptr = f"/servers/{escape_pointer_token(name)}"
            host = node.get("host") or node.get("url")
            self.add(
                "servers",
                AsyncApiServer(
                    location=self.loc(doc.path, sptr),
                    pointer=sptr,
                    name=name,
                    host=host if isinstance(host, str) else None,
                    protocol=(
                        node.get("protocol")
                        if isinstance(node.get("protocol"), str)
                        else None
                    ),
                ),
            )

    def run(self, paths: Sequence[str] | None) -> AsyncApiProjectModel:
        if paths is None:
            files = [
                p
                for p in self.context.iter_files()
                if p.lower().endswith(_DISCOVERY_SUFFIXES)
                and not any(part in _SKIP_DIRS for part in p.split("/"))
            ]
        else:
            files = list(paths)
        for path in files:
            doc = self.load(path, explicit=paths is not None)
            if doc is None or doc.status is not AsyncDocumentStatus.PARSED:
                continue
            family = doc.family or ""
            if family.startswith("2."):
                self._channels_2x(doc)
            else:
                self._channels_3x(doc)
            self._components(doc)
            self._servers(doc)
        def _info(d: _Doc) -> dict[str, Any]:
            info = d.value.get("info") if isinstance(d.value, dict) else None
            return info if isinstance(info, dict) else {}

        documents = tuple(
            AsyncApiDocument(
                location=self.loc(p),
                status=d.status,
                asyncapi_version=d.version,
                version_family=d.family,
                title=_info(d).get("title")
                if isinstance(_info(d).get("title"), str)
                else None,
                api_version=_info(d).get("version")
                if isinstance(_info(d).get("version"), str)
                else None,
            )
            for p, d in sorted(self.docs.items())
        )
        def _ordered(bucket: str) -> tuple[Any, ...]:
            items = self.out.get(bucket, [])
            return tuple(
                sorted(items, key=lambda i: (i.location.path, i.pointer))
            )

        return AsyncApiProjectModel(
            documents=documents,
            channels=_ordered("channels"),
            operations=_ordered("operations"),
            messages=_ordered("messages"),
            schemas=_ordered("schemas"),
            servers=_ordered("servers"),
            security_requirements=_ordered("security_requirements"),
            issues=tuple(
                sorted(self.issues, key=lambda i: (i.location.path, i.code.value, i.message))
            ),
        )


def load_asyncapi_project(
    context: ProjectContext, paths: Sequence[str] | None = None
) -> AsyncApiProjectModel:
    """Parse AsyncAPI documents under `context`. Never raises, never fetches."""
    return _Builder(context).run(paths)
