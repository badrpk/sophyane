# Implementation plan: guarded executable RSI

1. Add bridge tests for observation validation, explicit execution, and the
   invariant that ledger recording alone cannot execute mutation.
2. Add a small Mode-6 executor that converts validated observations into the
   existing `WeaknessRecord` and delegates one iteration to the existing
   `Controller`/`CodingRouter` path.
3. Add host-adjudicated RED state classification and an acceptance gate that
   combines focused GREEN, frozen holdout, regression, authority, and file
   policy evidence.
4. Add an immutable benchmark manifest and deterministic scoring/evidence
   records.
5. Add the explicit bounded campaign API with a hard maximum of 20, accepted
   generation chaining, rejection retention, stop conditions, and JSONL
   evidence.
6. Add deterministic fake-provider campaign tests and a sandboxed single
   iteration fixture; run the focused Mode-6 and existing RSI suites.

Self-review: the bridge uses the repository's existing `ImprovementObservation`,
`WeaknessRecord`, `Controller`, `Candidate`, `CodingRouter`, `verification`,
`promotion`, and `Journal` names. It does not make observations trusted,
does not duplicate provider selection, does not mutate the live repository in
simulation, and does not claim Level 4 without benchmark evidence.
