#!/usr/bin/env python3
"""Analyze positive and negative factors inside FR -> FL loops.

This analysis pools all agents.  It uses reference targets only to evaluate
when localization first becomes fault-relevant; it does not use them to
redefine the Pre-12 subtask boundaries.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAIR_FILE = ROOT / "RQ1/data/rq1_2/mechanisms/preloop_pairs.csv"
TRAJECTORY_FILE = ROOT / "pre/pre-12/dataset/pre12_trajectories.csv"
OUT = ROOT / "RQ1/data/rq1_2/factors"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def loop_band(k: int) -> str:
    if k <= 2:
        return str(k)
    if k <= 4:
        return "3-4"
    return "5+"


def position_band(index: int) -> str:
    if index <= 3:
        return str(index)
    if index <= 5:
        return "4-5"
    return "6+"


def first_relevant_band(rows: list[dict[str, str]]) -> str:
    positions = [
        int(row["pair_index"])
        for row in rows
        if row["fl_progress"] == "first_reference_target"
    ]
    if not positions:
        return "never"
    if positions[0] <= 2:
        return str(positions[0])
    return "3+"


def main() -> None:
    trajectories = read_csv(TRAJECTORY_FILE)
    complete = {
        (row["agent"], row["instance_id"]): int(row["resolved"])
        for row in trajectories
        if row["complete_repair"] == "1"
    }
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(PAIR_FILE):
        key = (row["agent"], row["instance_id"])
        if key in complete:
            grouped[key].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["pair_index"]))

    timing_records: list[dict[str, object]] = []
    for key, resolved in complete.items():
        rows = grouped.get(key, [])
        timing_records.append(
            {
                "loop_band": loop_band(len(rows)),
                "first_fault_relevant_localization": first_relevant_band(rows),
                "resolved": resolved,
            }
        )

    timing_summary: list[dict[str, object]] = []
    for band in ("1", "2", "3-4", "5+"):
        band_rows = [row for row in timing_records if row["loop_band"] == band]
        for timing in ("1", "2", "3+", "never"):
            selected = [
                row
                for row in band_rows
                if row["first_fault_relevant_localization"] == timing
            ]
            if not selected:
                continue
            timing_summary.append(
                {
                    "loop_band": band,
                    "first_fault_relevant_localization": timing,
                    "n": len(selected),
                    "share": round(len(selected) / len(band_rows), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    ),
                }
            )

    position_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rows in grouped.values():
        for row in rows:
            position_groups[position_band(int(row["pair_index"]))].append(row)

    marginal_summary: list[dict[str, object]] = []
    for band in ("1", "2", "3", "4-5", "6+"):
        rows = position_groups[band]
        progress = defaultdict(int)
        for row in rows:
            progress[row["fl_progress"]] += 1
        correct_gain = progress["first_reference_target"] + progress["additional_reference_target"]
        confirmation = progress["reference_target_confirmation"]
        no_gain = progress["no_reference_target_gain"]
        marginal_summary.append(
            {
                "cycle_position": band,
                "n": len(rows),
                "new_candidate_rate": round(
                    sum(bool(row["new_target_paths"]) for row in rows) / len(rows), 4
                ),
                "new_fault_relevant_target_rate": round(correct_gain / len(rows), 4),
                "fault_relevant_confirmation_rate": round(confirmation / len(rows), 4),
                "no_fault_relevant_gain_rate": round(no_gain / len(rows), 4),
            }
        )

    write_csv(OUT / "first_fault_relevant_localization.csv", timing_summary)
    write_csv(OUT / "marginal_localization_yield.csv", marginal_summary)
    print(f"Wrote {len(timing_summary)} timing rows and {len(marginal_summary)} yield rows to {OUT}")


if __name__ == "__main__":
    main()
