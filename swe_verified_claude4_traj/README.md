# SWE-bench Verified Claude 4 Trajectory Analysis

This project analyzes existing public trajectories from three open-source agent systems on SWE-bench Verified. We do not run agents, download agent repositories, or re-evaluate patches. The current scope is offline trajectory parsing, annotation, and analysis.

## Data Selection

We use public submissions from the official SWE-bench Verified leaderboard/experiments repository. The selection criteria are:

- Same benchmark split: SWE-bench Verified, 500 instances.
- Same base model: `claude-4-sonnet-20250514`.
- Public trajectories are available.
- Agent/system is marked open-source in official metadata.
- The systems are among the top-ranked submissions satisfying the above constraints.

Selected systems:

| Short name | System | Submission ID | Score | Resolved |
| --- | --- | --- | ---: | ---: |
| `lingxi` | Lingxi v1.5 + Claude 4 Sonnet | `20250720_Lingxi-v1.5_claude-4-sonnet-20250514` | 74.60 | 373/500 |
| `moatless` | Moatless Tools + Claude 4 Sonnet | `20250611_moatless_claude-4-sonnet-20250514` | 70.80 | 354/500 |
| `openhands` | OpenHands + Claude 4 Sonnet | `20250524_openhands_claude_4_sonnet` | 70.40 | 352/500 |

## Directory Layout

```text
swe_verified_claude4_traj/
  README.md
  data/
    official/
      agents.csv
      results/
      manifests/
    raw/
      lingxi/
      moatless/
      openhands/
    processed/
  scripts/
  notes/
```

## Meaning of Each Directory

| Path | Meaning |
| --- | --- |
| `data/official/` | Small official files used to identify and label the dataset. |
| `data/official/agents.csv` | Metadata table for the three selected systems. |
| `data/official/results/` | Official `results.json` files, used to label each instance as resolved/unresolved/no-generation/no-log. |
| `data/official/manifests/` | File lists for public trajectories. These are manifests, not trajectory contents. |
| `data/raw/` | Original downloaded trajectories. These files should not be modified. |
| `data/raw/lingxi/` | Raw Lingxi trajectory files. |
| `data/raw/moatless/` | Raw Moatless trajectory files. |
| `data/raw/openhands/` | Raw OpenHands trajectory files. |
| `data/processed/` | Normalized outputs produced by parsers. |
| `scripts/` | Downloading, parsing, and analysis scripts. |
| `notes/` | Research notes, taxonomy drafts, and data-selection notes. |

## Current Rule

Keep this workspace trajectory-focused:

- Do not download agent repositories here.
- Do not clone benchmark runners here.
- Do not create virtual environments until a script actually needs one.
- Keep original trajectories under `data/raw/`.
- Put derived tables under `data/processed/`.
