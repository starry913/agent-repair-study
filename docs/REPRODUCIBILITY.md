# Research artifact verification

This release preserves the existing analysis snapshot and makes its verification status explicit. The checks below were run with Python 3.10.12, DuckDB 1.5.2, NumPy 2.2.6, and SciPy 1.15.3.

## Verified from the included snapshot

- All 1,500 agent–instance keys are unique; each system has 500 records.
- Final labels agree with the included official submission results: 373, 354, and 352 resolved instances.
- Action and subtask row counts agree with trajectory-level counts: 155,836 actions, 21,142 subtasks, and 1,491 complete repair trajectories.
- Product-source and diagnostic-artifact boundary checks pass for all 1,696 refinement records.
- RQ2 transition tables can be independently reconstructed from ordered subtasks: 6,287 `FR → FL`, 1,425 latest-`FL`/first-`PC` pairs, 1,683 `PV → PR`, and 1,673 `PV → PR → PV` triples.
- Running `RQ2/rq2_recompute.py`, `RQ1/rq1_2_preloop_factor_analysis.py`, and `RQ1/rq1_2_deep_loop_analysis.py` regenerated 32 existing CSV files with identical SHA-256 hashes.
- The three core tables under `pre/pre-12/dataset/` are byte-identical to the included `data/processed/pre12/` copies.
- All 12 existing unit tests passed. These cover execution-outcome parsing and final-patch extraction, not the semantic validity of every annotation.
- The download manifest check found all 500 raw files for each of the three agents. Paths were made portable across checkout locations.

Run `python3 scripts/verify_snapshot.py` to repeat the core consistency checks.

## Raw-to-label rebuild: known drift

A full run of the current `pre12_recompute.py` against the included raw trajectories and the locally cached SWE-bench Verified reference data produced the same trajectory table and the same action/subtask counts, but did **not** reproduce all stored labels. The rebuild was written to a separate directory; the research snapshot was not overwritten.

The reference Parquet used for this check has SHA-256 `a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`. Its derived reference-metadata CSV was byte-identical to the included metadata. This is evidence of parser/snapshot drift, rather than a changed reference-metadata table.

| Comparison | Result |
| --- | ---: |
| Generated files matching the stored processed snapshot exactly | 8 / 14 |
| Action rows whose `outcome` field differs | 17,601 / 155,836 |
| Subtask rows whose `local_outcome` differs | 319 / 21,142 |
| Subtask rows whose `local_outcome_basis` differs | 729 / 21,142 |
| Trajectory table | Byte-identical |
| Reference-metadata table | Byte-identical |

Some action changes are representation differences (`unknown` versus an empty value); others change pass/fail/unknown classification. They must not all be interpreted as changed test results.

| Subtask/outcome | Included snapshot | Current parser rebuild |
| --- | ---: | ---: |
| `FR+` | 4,074 | 3,979 |
| `FR-` | 3,036 | 3,131 |
| `FR?` | 368 | 368 |
| `PR+` | 1,061 | 1,116 |
| `PR-` | 629 | 554 |
| `PR?` | 6 | 26 |

`PU`, `FL`, `PC`, and `PV` local-label counts are unchanged. Product-source boundary checks still pass in the rebuild. The changed files are `pre12_actions.csv`, `pre12_subtasks.csv`, the pooled and per-agent local-outcome summaries, the refinement-quality summary, and the generated report.

## Consequences for interpretation

The README reports the **included snapshot's** measurements. Snapshot-level recomputation and end-to-end raw-log reproducibility are distinct claims: the former is verified for the commands above, while the latter remains incomplete.

The first-patch association and trajectory-level loop statistics survive this rebuild unchanged. Results involving reproduction/refinement labels or actual execution feedback need a sensitivity analysis after reconciling the parser and snapshot. In particular, the `PV+ → PR+` feedback percentages should be treated as provisional measurements from the frozen annotations.

Before making a new canonical release, review changed labels against raw evidence, decide which parsing rules define the next annotation version, regenerate all downstream tables consistently, and update the findings. This repository does not claim that work has already been completed.

## Repeat the rebuild without replacing the snapshot

```bash
export SWE_BENCH_VERIFIED_PARQUET=/absolute/path/to/reference.parquet
PRE12_OUT_DIR=/tmp/agent-repair-rebuild python3 swe_verified_claude4_traj/scripts/pre12_recompute.py
diff -u swe_verified_claude4_traj/data/processed/pre12/pre12_local_outcomes.csv /tmp/agent-repair-rebuild/pre12_local_outcomes.csv
```

The explicit reference-file setting is also supported by the task-scope and reference-patch analysis loaders. No reference data is obtained from the user's private GitHub account.
