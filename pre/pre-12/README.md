# Pre-12 Dataset

Taxonomy version: `pre12_frfl_prdelta_reason2_outcome3`.

This directory stores the finalized Pre-12 trajectory abstraction results.

## Directory layout

| Directory | Content |
| --- | --- |
| `dataset/` | Core trajectory abstraction dataset. Use these files for RQ analysis. |
| `summary/` | Derived summary tables generated from `dataset/`. |
| `metadata/` | Reference patch metadata and the generated Pre-12 report. |

## Core dataset files

| File | Unit | Meaning |
| --- | --- | --- |
| `dataset/pre12_actions.csv` | action record | Event-level action abstraction, including creation, path-type, diagnostic-artifact, and product-source flags. |
| `dataset/pre12_subtasks.csv` | subtask record | Consecutive actions grouped into subtasks, with local outcome. |
| `dataset/pre12_trajectories.csv` | agent-instance trajectory | One row per agent-instance trajectory, with canonical path and final resolved label. |

## Metadata

| File | Meaning |
| --- | --- |
| `metadata/pre12_reference_patch_meta.csv` | SWE-bench Verified reference patch files, test files, and FAIL_TO_PASS tests used for oracle-aligned labeling. |
| `metadata/pre12_report.md` | Basic statistics for the finalized Pre-12 dataset. |

## Summary tables

Files under `summary/` are derived tables for quick inspection only. They should be regenerated from `dataset/` if the taxonomy changes.

`summary/pre12_pr_quality.csv` records the PR boundary checks. In the finalized data, no `PR` segment contains a diagnostic-material edit, and `PR?` is reserved for unavailable refinement content.
