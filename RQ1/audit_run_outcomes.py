#!/usr/bin/env python3
"""Audit Run outcome changes introduced by the test-output parser fix."""

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OLD_ACTIONS = ROOT / "pre" / "pre-12" / "dataset" / "pre12_actions.csv"
OUT_DIR = ROOT / "RQ1" / "audit"
sys.path.insert(0, str(TRAJ_ROOT))

from scripts import pre12_recompute as pre  # noqa: E402


def read_old_outcomes():
    outcomes = {}
    with OLD_ACTIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["action"] == "Run":
                key = (row["agent"], row["instance_id"], int(row["event_index"]))
                outcomes[key] = row["outcome"] or "unknown"
    return outcomes


def compact(text, limit=360):
    return " ".join(str(text or "").split())[:limit]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    old = read_old_outcomes()
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_outcome_audit"))
    changed = []
    transition_counts = Counter()
    for agent, instance_id, _, events, _ in pre.load_all(TRAJ_ROOT, refs):
        for event in events:
            if event["action"] != "Run":
                continue
            key = (agent, instance_id, event["event_index"])
            old_outcome = old.get(key, "missing")
            new_outcome = event.get("outcome") or "unknown"
            if old_outcome == new_outcome:
                continue
            transition_counts[(agent, old_outcome, new_outcome)] += 1
            changed.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "event_index": event["event_index"],
                    "old_outcome": old_outcome,
                    "new_outcome": new_outcome,
                    "cue": event.get("cue", ""),
                    "command": compact(event.get("command", ""), 240),
                    "evidence": compact(event.get("text", "")),
                }
            )

    summary = [
        {
            "agent": agent,
            "old_outcome": old_outcome,
            "new_outcome": new_outcome,
            "n": n,
        }
        for (agent, old_outcome, new_outcome), n in sorted(transition_counts.items())
    ]
    write_csv(OUT_DIR / "run_outcome_changes.csv", changed)
    write_csv(OUT_DIR / "run_outcome_change_summary.csv", summary)
    print(f"changed_run_events={len(changed)}")
    for row in summary:
        print(
            f"{row['agent']}: {row['old_outcome']} -> "
            f"{row['new_outcome']} = {row['n']}"
        )


if __name__ == "__main__":
    main()
