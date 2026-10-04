"""Artifact discovery + classification (§13).

One filesystem walk produces a classified inventory every analyzer
consumes — no per-analyzer `iter_files` scans. Classification uses
strong markers only: well-known names, extensions, and content markers
sniffed from a bounded head read (never a full parse, never name
similarity).

Classes are permissive *enabling* signals: a file marked CONTRACT is a
candidate the contract parsers re-verify with their own authoritative
detection. Marking errs toward enabling a domain, never toward
inventing evidence — a false-positive class costs one cheap analyzer
pass; a false-negative loses findings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.runtime.loader import ADAPTERS
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Model


class ArtifactClass(StrEnum):
    """Stable artifact roles (§13). A file may carry several classes."""

    SOURCE = "source"
    CONTRACT = "contract"
    RUNTIME = "runtime"
    IAC = "iac"
    GATEWAY = "gateway"
    MESH = "mesh"
    POLICY = "policy"
    CONFIG = "config"
    CLIENT = "client"
    WORKSPACE = "workspace"
    OWNERSHIP = "ownership"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


# Stable marker tags — plan rules (core/plan.py) match on these.
MARKER_OPENAPI = "openapi"
MARKER_SWAGGER = "swagger"
MARKER_ASYNCAPI = "asyncapi"
MARKER_PROTO = "proto"
MARKER_GRAPHQL = "graphql"
MARKER_TERRAFORM = "terraform"
MARKER_KUBERNETES = "kubernetes"
MARKER_KONG = "kong"
MARKER_ENVOY = "envoy"
MARKER_NGINX = "nginx"
MARKER_TRAEFIK = "traefik"
MARKER_ISTIO = "istio"
MARKER_LINKDERD = "linkerd"
MARKER_POLICY = "policy"
MARKER_CODEOWNERS = "codeowners"
MARKER_WORKSPACE = "workspace-manifest"
MARKER_BUILD_MANIFEST = "build-manifest"

# Directories whose files are recorded but flagged `vendored` — matching
# the skip convention analyzers already use (`_SKIP_DIRS`, hidden parts).
_VENDOR_PARTS = frozenset({
    "node_modules", "__pycache__", "site-packages", "dist", "build",
    "vendor", "venv", ".venv",
})

_HEAD_BYTES = 4096

_YAML_JSON_SUFFIXES = frozenset({".yaml", ".yml", ".json"})
_RUNTIME_SNIFF_SUFFIXES = _YAML_JSON_SUFFIXES | {".log", ".ndjson", ".txt"}

_SOURCE_SUFFIXES: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
}
_JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
# Client scanners cover python + javascript-family source only.
_CLIENT_SUFFIXES = _JS_SUFFIXES | {".py"}

_DOC_SUFFIXES = {".md", ".rst", ".adoc"}

_WORKSPACE_NAMES = {
    "forge-doctor-api.workspace.yaml", "forge-doctor-api.workspace.yml",
    "workspace.yaml", "workspace.yml",
}
_OWNERSHIP_NAMES = {"codeowners", "owners"}
_BUILD_MANIFEST_NAMES = {
    "pom.xml", "build.gradle", "build.gradle.kts", "package.json",
    "go.mod", "cargo.toml", "pyproject.toml", "setup.py", "setup.cfg",
    "gemfile", "composer.json",
}

# yaml/json markers: (marker-tag, needle candidates). Matched against the
# decoded head text, case-insensitive, line-anchored — permissive on
# purpose (analyzers re-verify); a match only *enables* a domain.
_CONTRACT_NEEDLES = {
    MARKER_OPENAPI: ("openapi:", '"openapi"', "openapi :"),
    MARKER_SWAGGER: ("swagger:", '"swagger"'),
    MARKER_ASYNCAPI: ("asyncapi:", '"asyncapi"'),
}
_K8S_NEEDLES = ("apiversion:", "kind:")
_ISTIO_NEEDLES = (
    "virtualservice", "destinationrule", "gateway.networking.istio.io",
    "istio.io", "serviceentry", "authorizationpolicy",
)
_LINKDERD_NEEDLES = ("serviceprofile", "linkerd.io")
_GATEWAY_NEEDLES = {
    MARKER_KONG: ("_format_version", "kong"),
    MARKER_ENVOY: ("static_resources", "envoy"),
    MARKER_TRAEFIK: ("traefik", "http.routers", "providers:"),
    "aws-apigateway": ("x-amazon-apigateway",),
}
_POLICY_NEEDLE = "policies:"


def _vendored(path: str) -> bool:
    return any(
        part.startswith(".") or part in _VENDOR_PARTS
        for part in path.split("/")[:-1]
    )


def _sniff_head(context: ProjectContext, path: str) -> tuple[str, str | None, bool]:
    """Return (decoded-head-text, runtime-adapter-name, opened) from <=4KB.

    Text decode failures yield an empty head; adapter detection reuses
    the runtime adapters' own strong-marker gates.
    """
    fh = context.open_binary(path)
    if fh is None:
        return "", None, False
    with fh:
        head = fh.read(_HEAD_BYTES)
    adapter = next((a for a in ADAPTERS if a.detect(path, head)), None)
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    return text, (adapter.name if adapter else None), True


def _classify_data_file(head: str) -> tuple[set[ArtifactClass], set[str]]:
    """Marker rules for yaml/json content (head text, lowercased)."""
    classes: set[ArtifactClass] = set()
    markers: set[str] = set()
    lower = head.lower()
    for marker, needles in _CONTRACT_NEEDLES.items():
        if any(n in lower for n in needles):
            classes.add(ArtifactClass.CONTRACT)
            markers.add(marker)
    if all(n in lower for n in _K8S_NEEDLES):
        classes.add(ArtifactClass.IAC)
        markers.add(MARKER_KUBERNETES)
    if any(n in lower for n in _ISTIO_NEEDLES):
        classes.add(ArtifactClass.MESH)
        markers.add(MARKER_ISTIO)
    if any(n in lower for n in _LINKDERD_NEEDLES):
        classes.add(ArtifactClass.MESH)
        markers.add(MARKER_LINKDERD)
    for marker, needles in _GATEWAY_NEEDLES.items():
        if any(n in lower for n in needles):
            classes.add(ArtifactClass.GATEWAY)
            markers.add(marker)
    if _POLICY_NEEDLE in lower:
        classes.add(ArtifactClass.POLICY)
        markers.add(MARKER_POLICY)
    return classes, markers


@dataclass(frozen=True, kw_only=True)
class Artifact(Model):
    """One discovered file: classes + the markers that produced them."""

    path: str
    classes: tuple[ArtifactClass, ...]
    markers: tuple[str, ...] = ()
    vendored: bool = False
    unreadable: bool = False


@dataclass(frozen=True, kw_only=True)
class ArtifactInventory(Model):
    """The classified result of one filesystem walk (§13)."""

    artifacts: tuple[Artifact, ...] = ()

    def artifact(self, path: str) -> Artifact | None:
        for a in self.artifacts:
            if a.path == path:
                return a
        return None

    def files_in(
        self, *classes: ArtifactClass, include_vendored: bool = False
    ) -> list[str]:
        """Sorted paths carrying any of `classes` (vendored excluded)."""
        return [
            a.path
            for a in self.artifacts
            if (include_vendored or not a.vendored)
            and any(c in a.classes for c in classes)
        ]

    def has_class(self, cls: ArtifactClass) -> bool:
        return any(not a.vendored and cls in a.classes for a in self.artifacts)

    def markers(self) -> frozenset[str]:
        return frozenset(
            m for a in self.artifacts if not a.vendored for m in a.markers
        )

    def counts_by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.artifacts:
            if a.vendored:
                continue
            for c in a.classes:
                counts[c.value] = counts.get(c.value, 0) + 1
        return dict(sorted(counts.items()))


def _classify(
    context: ProjectContext, path: str
) -> tuple[tuple[ArtifactClass, ...], tuple[str, ...], bool]:
    """Classify one path. Returns (classes, markers, unreadable)."""
    lower_path = path.lower()
    name = lower_path.rsplit("/", 1)[-1]
    suffix = ""
    if "." in name:
        suffix = "." + name.rsplit(".", 1)[-1]

    classes: set[ArtifactClass] = set()
    markers: set[str] = set()

    if name in _OWNERSHIP_NAMES:
        classes.add(ArtifactClass.OWNERSHIP)
        markers.add(MARKER_CODEOWNERS)
    if name in _WORKSPACE_NAMES:
        classes.add(ArtifactClass.WORKSPACE)
        markers.add(MARKER_WORKSPACE)
    if name in _BUILD_MANIFEST_NAMES or name.startswith("requirements"):
        classes.add(ArtifactClass.CONFIG)
        markers.add(MARKER_BUILD_MANIFEST)

    if suffix == ".proto":
        classes.add(ArtifactClass.CONTRACT)
        markers.add(MARKER_PROTO)
    elif suffix in (".graphql", ".gql"):
        classes.add(ArtifactClass.CONTRACT)
        markers.add(MARKER_GRAPHQL)
    elif suffix == ".tf":
        classes.add(ArtifactClass.IAC)
        markers.add(MARKER_TERRAFORM)
    elif suffix == ".conf" or name == "nginx.conf":
        classes.add(ArtifactClass.GATEWAY)
        markers.add(MARKER_NGINX)

    if suffix in _SOURCE_SUFFIXES:
        classes.add(ArtifactClass.SOURCE)
        markers.add(_SOURCE_SUFFIXES[suffix])
    elif suffix in _JS_SUFFIXES:
        classes.add(ArtifactClass.SOURCE)
        markers.add("javascript")
    if suffix in _CLIENT_SUFFIXES:
        classes.add(ArtifactClass.CLIENT)
    if suffix in _DOC_SUFFIXES:
        classes.add(ArtifactClass.DOCUMENTATION)

    unreadable = False
    if suffix in _YAML_JSON_SUFFIXES:
        classes.add(ArtifactClass.CONFIG)
    if suffix in _RUNTIME_SNIFF_SUFFIXES:
        head, adapter_name, opened = _sniff_head(context, path)
        unreadable = not opened
        if adapter_name is not None:
            classes.add(ArtifactClass.RUNTIME)
            markers.add(adapter_name)
        if suffix in _YAML_JSON_SUFFIXES and head:
            data_classes, data_markers = _classify_data_file(head)
            classes.update(data_classes)
            markers.update(data_markers)

    if not classes:
        classes.add(ArtifactClass.UNKNOWN)
    return (
        tuple(sorted(classes)),
        tuple(sorted(markers)),
        unreadable,
    )


def discover(context: ProjectContext) -> ArtifactInventory:
    """One sorted walk -> the classified inventory (§13)."""
    artifacts: list[Artifact] = []
    for path in context.iter_files():
        classes, markers, unreadable = _classify(context, path)
        artifacts.append(
            Artifact(
                path=path,
                classes=classes,
                markers=markers,
                vendored=_vendored(path),
                unreadable=unreadable,
            )
        )
    return ArtifactInventory(artifacts=tuple(artifacts))
