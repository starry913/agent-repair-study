# RQ1.1 Discordance Analysis

Unit of analysis: one `trajectory x subtask anchor`.

| Subtask | Anchor |
| --- | --- |
| `PU` | first segment |
| `FR` | last segment |
| `FL` | last segment |
| `PC` | first segment |
| `PR` | last segment |
| `PV` | last segment |

This prevents long trajectories from contributing the same subtask repeatedly.
`positive_unresolved` denotes `+ / unresolved`; `negative_resolved` denotes
`- / resolved`.

## Files

| File | Meaning |
| --- | --- |
| `discordant_anchor_cases.csv` | All discordant anchors and observable evidence |
| `discordant_anchor_summary.csv` | Cell size and agent distribution |
| `discordance_mechanism_cases.csv` | Rule-derived mechanism-case links |
| `discordance_mechanism_summary.csv` | Mechanism count, share, agent split, and examples |
| `final_patches/manifest.csv` | Availability and provenance of reconstructed final patches |
| `patch_mechanism_cases.csv` | Candidate/reference final-patch comparison |
| `patch_mechanism_summary.csv` | Patch-profile distribution in `PC` and `PR` discordance cells |
| `matched_final_patch_summary.csv` | Same-instance resolved/unresolved final-patch comparison |
| `semantic_coding_sample.csv` | Stratified sample for manual semantic coding |
| `semantic_coding_sample.json` | Sampling seed and allocation |
| `mechanism_casebook.jsonl` | Compact raw-evidence packets for case verification |

## Interpretation

The automatic mechanisms are evidence profiles, not causal labels. Shares are
additive only where the mechanism rules are explicitly mutually exclusive.
Semantic adequacy of problem understanding and patch behavior requires the
manual coding sample; lexical or file overlap alone is not treated as semantic
correctness.

Lingxi's public trajectories do not retain command stdout/stderr. Its run
outcomes remain unknown unless a structured observation is present; reasoning
text is not substituted for tool output.
