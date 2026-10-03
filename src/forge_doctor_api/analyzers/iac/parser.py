"""§74-76 IaC/Kubernetes manifest extraction.

Kubernetes: every YAML doc with `apiVersion`+`kind`+`metadata.name`.
Chains are built only on declared identifiers — `backend.service.name`,
`spec.selector` ↔ `metadata.labels` byte equality — never name
similarity. Terraform: `resource "TYPE" "NAME"` line scan only (no HCL
evaluation). Helm: `Chart.yaml` markers. CloudFormation: recorded as
deferred per §74.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from forge_doctor_api.analyzers.iac.model import (
    ChainLink,
    IacResource,
    InfraModel,
    K8sKind,
    KubernetesResource,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_KNOWN = {k.value: k for k in K8sKind}
_TF_RESOURCE = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"')
_CFN_MARKERS = ("AWSTemplateFormatVersion", '"AWS::', "Resources:")


def _loc(path: str) -> SourceLocation:
    return SourceLocation(path=path, line=None)


def _labels(meta: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    labels = meta.get("labels") or {}
    if not isinstance(labels, dict):
        return ()
    return tuple(sorted(
        (str(k), str(v)) for k, v in labels.items()))


def _k8s_resource(path: str, doc: dict[str, Any]) -> KubernetesResource | None:
    kind_raw = doc.get("kind")
    meta = doc.get("metadata") or {}
    api = str(doc.get("apiVersion") or "")
    name = meta.get("name")
    if not kind_raw or not name or not api:
        return None
    kind = _KNOWN.get(str(kind_raw), K8sKind.OTHER)
    spec = doc.get("spec") or {}
    selectors: tuple[tuple[str, str], ...] = ()
    backends: list[str] = []
    if kind is K8sKind.SERVICE:
        sel = spec.get("selector") or {}
        if isinstance(sel, dict):
            selectors = tuple(sorted(
                (str(k), str(v)) for k, v in sel.items()))
    if kind is K8sKind.INGRESS:
        for rule in spec.get("rules") or ():
            for p in ((rule.get("http") or {}).get("paths") or ()):
                backend = p.get("backend") or {}
                svc = backend.get("service") or {}
                if svc.get("name"):
                    backends.append(str(svc["name"]))
                elif backend.get("serviceName"):
                    backends.append(str(backend["serviceName"]))
        defb = spec.get("defaultBackend") or {}
        ds = defb.get("service") or {}
        if ds.get("name"):
            backends.append(str(ds["name"]))
    if kind is K8sKind.HTTPROUTE:
        for rule in spec.get("rules") or ():
            for b in rule.get("backendRefs") or ():
                if isinstance(b, dict) and b.get("name"):
                    backends.append(str(b["name"]))
    if kind is K8sKind.DEPLOYMENT:
        sel = spec.get("selector") or {}
        match = sel.get("matchLabels") or {}
        if isinstance(match, dict):
            selectors = tuple(sorted(
                (str(k), str(v)) for k, v in match.items()))
    return KubernetesResource(
        kind=kind, api_version=api, name=str(name),
        namespace=(str(meta["namespace"]) if meta.get("namespace") else None),
        labels=_labels(meta), selectors=selectors,
        backends=tuple(dict.fromkeys(backends)),
        location=_loc(path))


def _chains(
    resources: tuple[KubernetesResource, ...],
) -> tuple[tuple[ChainLink, ...], tuple[UnknownFact, ...]]:
    links: list[ChainLink] = []
    unknowns: list[UnknownFact] = []
    services = {r.name: r for r in resources if r.kind is K8sKind.SERVICE}
    deployments = [
        r for r in resources if r.kind is K8sKind.DEPLOYMENT]
    front = [r for r in resources
             if r.kind in (K8sKind.INGRESS, K8sKind.HTTPROUTE,
                           K8sKind.GATEWAY)]
    for f in front:
        fid = f"{f.kind.value}/{f.name}"
        if not f.backends and f.kind is not K8sKind.GATEWAY:
            unknowns.append(UnknownFact(
                subject=fid, missing="backend service reference",
                resolution="declare backend.service.name / backendRefs"))
            continue
        for be in f.backends:
            svc = services.get(be)
            if svc is None:
                unknowns.append(UnknownFact(
                    subject=fid,
                    missing=f"backend service '{be}' in manifests",
                    resolution="the referenced Service is not in scope"))
                continue
            sid = f"Service/{svc.name}"
            links.append(ChainLink(
                source=fid, target=sid, via="backend",
                location=svc.location))
            matched = False
            for dep in deployments:
                shared = set(svc.selectors) & set(dep.selectors)
                if shared:
                    links.append(ChainLink(
                        source=sid, target=f"Deployment/{dep.name}",
                        via="selector:" + ",".join(
                            f"{k}={v}" for k, v in sorted(shared)),
                        location=dep.location))
                    matched = True
            if not matched and svc.selectors:
                unknowns.append(UnknownFact(
                    subject=sid,
                    missing="Deployment matching the selector",
                    resolution="no Deployment selector overlaps"))
    return tuple(links), tuple(unknowns)


def load_infra_model(
    context: ProjectContext, files: list[str],
) -> InfraModel:
    """Scan committed manifests + IaC into an `InfraModel` (§74-76)."""
    kube: list[KubernetesResource] = []
    iac: list[IacResource] = []
    issues: list[str] = []
    unknowns: list[UnknownFact] = []
    for rel in sorted(files):
        suffix = Path(rel).suffix.lower()
        name = Path(rel).name
        if suffix == ".tf":
            try:
                text = context.read_text(rel)
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                m = _TF_RESOURCE.match(line)
                if m:
                    iac.append(IacResource(
                        iac_kind="terraform", type_name=m.group(1),
                        name=m.group(2),
                        location=SourceLocation(path=rel, line=i)))
            continue
        if name == "Chart.yaml":
            try:
                doc = yaml.safe_load(context.read_text(rel)) or {}
            except (yaml.YAMLError, OSError, UnicodeDecodeError):
                doc = {}
            iac.append(IacResource(
                iac_kind="helm",
                type_name="chart",
                name=str(doc.get("name") or Path(rel).parent.name),
                location=_loc(rel)))
            continue
        if suffix not in (".yaml", ".yml", ".json"):
            continue
        try:
            text = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            continue
        if any(m in text for m in _CFN_MARKERS):
            iac.append(IacResource(
                iac_kind="cloudformation", type_name="template",
                name=name, location=_loc(rel), parsed=False))
            issues.append(
                f"{rel}: CloudFormation detection deferred per §74")
            continue
        try:
            docs = list(yaml.safe_load_all(text))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            res = _k8s_resource(rel, doc)
            if res is not None:
                kube.append(res)
    chains, chain_unknowns = _chains(tuple(kube))
    return InfraModel(
        kubernetes=tuple(kube), chains=chains, iac=tuple(iac),
        issues=tuple(issues),
        unknowns=tuple([*unknowns, *chain_unknowns]))
