# Contract fixtures provenance

`forge-contracts-1-handoff.json` — canonical `forge-contracts/1`
handoff bundle fixture, vendored verbatim from the shared wire contract
(forge-doctor-data `src/forge_doctor_data/contracts/fixtures/handoff.json`,
2026-10). It is a contract artifact: editing it changes the wire
expectation, not the test. Verify parity with:

    python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" tests/fixtures/contracts/forge-contracts-1-handoff.json
