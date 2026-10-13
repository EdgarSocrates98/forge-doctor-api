# Engineering Excellence — Doctor API Diagnostics

## Boundary

Doctor API owns API diagnosis: analyzers, verifiers, findings, report, factory, lab, benchmarks and CLI. It reports evidence; it does not route business execution or auto-edit architecture.

## Diagnostic receipt

Every published finding should preserve:

- target and source digest;
- analyzer/verifier id and version;
- reproducible command or fixture;
- location and severity;
- observed failure and expected invariant;
- confidence, limitation and next action;
- architecture blast-radius estimate when known.

Unknown fields stay unknown. A green analyzer run is not proof of absence of defects outside analyzed scope.

## Federation

The Forge may consume capability descriptor and finding references. It must not reinterpret Doctor API rules or merge findings silently. `diagnostic-only` remains distinct from mutation workflows.

## Verification

```text
python -m pytest tests -q
python -m ruff check .
```

Prioritize tests for analyzer contracts, runtime evidence, report, security, reliability and UI resilience.

## Pending

- Publish diagnostic capability descriptor.
- Add stable receipt schema for analyzer/verifier provenance.
- Add one replay fixture per API risk class.
