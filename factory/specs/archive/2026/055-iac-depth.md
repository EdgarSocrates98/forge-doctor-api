---
id: 055-iac-depth
title: IaC intelligence depth — Terraform parsing + CloudFormation surface
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §61-§63, §74.
- Problem: `analyzers/iac/terraform.py` is a line scanner — it marks
  resource blocks but has no attribute-level extraction; CloudFormation
  is explicitly deferred (§74) with no parser at all.
- Out of scope: Kubernetes depth (k8s.py exists; spec 057 covers its
  linkage), Helm/Kustomize/SAM/CDK (§74 roadmap deferrals stay).
- Review failure: an HCL "parser" that is regex-on-raw-text (matches
  inside comments/strings); CFN YAML parsed without `!Ref` tag
  handling (pyyaml crash); fabricated attributes from resource type
  alone.
- Riskiest assumption: stdlib HCL feasibility — RESOLVED: a bounded
  HCL2 surface parser is in-spec ONLY if it strips comments/heredocs
  and extracts top-level block headers + simple `key = literal`
  attributes; anything nested/dynamic (count, for_each, expressions)
  → field `None` + UnknownFact, never a guess. If that bound breaks,
  emit the marker level only and record the unknown — do NOT add an
  hcl2 dependency.
- Smallest acceptable: Terraform attribute-level extraction for the
  existing resource set (aws_lb, aws_api_gateway*, aws_lambda, sg,
  route53, eks/ecs service) + CloudFormation YAML parser
  (Resources/Type/Properties, `!`-tag handling) + infra-model entries
  with attribute evidence + tests incl. adversarial.

# Context

§61-§63: infra intelligence from Terraform + CloudFormation. §74
explicit deferrals stay roadmap. §99: no fabricated resource
attributes.

# Acceptance Criteria

- `terraform.py`: comment/heredoc-stripping tokenizer → block headers
  + literal attributes; expression values → `None`+unknown; evidence
  per extracted field (file:line).
- `cloudformation.py`: YAML load with a `!`-tag constructor
  (ref/getatt/sub recorded as `{"Ref": ...}` shapes, marked dynamic),
  Resources → infra entities + attribute candidates + UnknownFacts
  for dynamic values.
- InfraModel entries gain evidence-backed fields (listeners, targets,
  security groups, subnets where literal); `dynamic` fields produce
  UnknownFact entries.
- Adversarial fixtures: commented blocks, string literals containing
  `resource "aws_lb"`, `count`-gated resources (existence UNKNOWN
  unless count literal >0 — documented rule), malformed HCL/YAML →
  parse-unknown not crash.
- pytest/ruff/mypy pass.

# Constraints

- Zero new deps; bounded parsing documented in module docstrings.
- Existence/attribute rules documented — dynamic → unknown.
