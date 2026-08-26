# Task 6 implementation report — independent direction settlement and read-only governance

## Implemented

- Added `direction_settlement.py` as an independent settlement boundary. It
  accepts only the repository's immutable formal finished/90min/official
  provenance/score contract. Bare H/D/A, offline scores, pending, unverified,
  non-90-minute, extra-time and penalty results remain `UNSETTLED`.
- Settlement requires a stored `REGISTERED`, available, timezone-aware
  prematch policy. `NOT_REGISTERED`, `UNAVAILABLE`, `UNCLEAR` and unsettled
  records never enter any hit denominator and no historical direction is
  recomputed from probabilities.
- Added separate `primary_hit`, `alternative_hit` and
  `direction_policy_hit` metrics. Primary denominator is every settled
  scoreable registered primary; alternative denominator is only settled
  `PRIMARY_WITH_COVER` policies with an alternative; coverage denominator is
  every settled scoreable registered policy.
- `fusion_backtest.py` now emits `direction_policy_metrics` without changing
  the existing Top1, Brier, LogLoss, ECE, CLV, ROI, EV or Kelly paths. A
  regression fixture proves a cover hit leaves the original Top1 accuracy at
  zero when the primary was wrong.
- Backtest alias matching now preserves Task 3's exact registered-route
  boundary. A conflicting/missing immutable route cannot be filled by an
  approved alias.
- `version_progress.py` now builds the combined read-only governance report:
  current identity, release-lock status, raw/approved-alias settled samples,
  exact alias route/attestation/field coverage, drift states, policy status and
  classification counts, three independent hit metrics and a fail-closed
  version admission conclusion.
- Added `fusion_cli.py direction-governance-report`. Its parser exposes only
  `--store` and `--snapshot-policy`; it has no output, alias approval, lock,
  weight or gate mutation option.

## TDD evidence

### RED 1 — settlement module

The initial settlement test collection failed with
`ModuleNotFoundError: direction_settlement`. After the minimal module was
implemented, all six initial settlement/status/denominator tests passed.

### RED 2 — report and CLI

The report/CLI tests then failed four ways: missing report builder, missing
read-only entrypoint, absent help entry and unknown command routing. After the
minimum integration, all six report/CLI tests passed.

### RED 3 — backtest isolation

The backtest integration test initially failed because the JSON report had no
`direction_policy_metrics`. After attaching stored policy settlement, the
fixture reported Top1 accuracy `0.0`, primary `0/1`, alternative `1/1` and
coverage `1/1` as independent values.

### RED 4 — exact route aliases and nested kickoff

- Removing the route-validity guard made the route-conflict regression fail:
  the alias incorrectly changed the row from legacy to current. Restoring the
  guard passed the test.
- A production-shaped record with kickoff only at `record.match.kickoff`
  initially produced zero direction denominators. Reading that immutable
  nested kickoff restored the required prematch validation and passed.

## Fresh verification

```text
Task 6 + direction/registration/alias/version/backtest regressions:
105 passed

P0 suite in its required isolated process:
26 passed, 6 subtests passed

py_compile for all four Task 6 scripts: passed
git diff --check: passed
version manifest / release lock / recommendation policy diff: empty
```

The monolithic test invocation produced `470 passed, 11 failed`. Re-running
`test_p0_evaluation.py` alone passed completely, confirming the previously
documented cross-checkout `sys.modules` contamination in combined collection.
The remaining independently reproducible failure is the pre-existing fixed
`2026-08-26T03:00:00Z` case in
`test_bb_browser_evidence_collect.py::test_collect_file_accepts_single_match_object`;
it is outside Task 6 and no Task 1 evidence code was changed.

## Scope and immutability

- No historical prediction, result, registry or shared store was written.
- No probability file, model version, probability signature definition,
  release lock, alias configuration, weight, calibration parameter,
  recommendation policy, EV/Kelly path or production gate changed.
- Direction coverage is explicitly labelled as policy-set coverage and is
  never presented as primary/model direction correctness or admission proof.

## Fix round 1/5 — formal result and projection hardening

Implementation commit: `524a413` (`fix: enforce formal direction settlement boundaries`).

### RED

The review regressions were written before production changes. The focused run
failed in five required places:

1. bare H/D/A and incomplete/untrusted result payloads could settle;
2. a missing or naive kickoff could still pass the prematch policy check;
3. offline `actual` was wrapped as `score_90_status=verified` and entered the
   direction denominator;
4. Task 6 had overwritten the pre-existing `mode` projection with exact route;
5. the governance report exposed registry-settled upper bounds as ambiguous
   settled counts, including aliases without verified official result files.

Observed RED result: `5 failed, 7 passed`.

### GREEN

- Direction settlement now calls the shared formal 90-minute validator and
  official Sporttery/user-confirmed provenance contract. It additionally
  rejects explicit extra-time/penalty fields and a present non-`verified`
  `score_90_status`.
- Both `prediction_as_of` and kickoff must be parseable timezone-aware values,
  with `prediction_as_of < kickoff`.
- Offline `actual` remains untouched for original Top1/Brier/etc. scoring, but
  only a separately supplied complete `official_result` can settle direction.
- The original `mode` projection and route stratification are restored exactly;
  exact alias identity remains isolated in `route` and
  `route_identity_valid`.
- The governance report now names registry values
  `*_registry_settled_upper_bound_n`, separately reports
  `*_verified_official_settled_n`, and alias summaries expose only
  `verified_official_settled_count`.

Fresh GREEN evidence after the fix:

```text
Focused RED-to-GREEN tests: 12 passed
Task 6 + direction/registration/alias/version/backtest regressions: 108 passed
P0 suite in isolated process: 26 passed, 6 subtests passed
py_compile for all four Task 6 scripts: passed
git diff --check: passed
version manifest / release lock / recommendation policy diff: empty
```

Mutation-style regression inputs cover bare directions, truthy unknown sources,
incomplete `score_90_status=verified` payloads, pending verification,
extra-time/penalty data, missing/invalid/naive kickoff, offline actual-only
records, output-only legacy mode projection, and registry-only alias settlement.
