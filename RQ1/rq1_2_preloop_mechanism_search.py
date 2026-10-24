#!/usr/bin/env python3
"""Explore non-oracle mechanisms that trigger repeated FR -> FL cycles.

The unit is not an isolated FR -> FL pair.  For every pair after the first,
we inspect why the trajectory returned from the preceding FL to another FR
and how the following FL changed.  Reference-patch fields are deliberately
excluded from mechanism assignment.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RQ1.rq1_2_mechanism_analysis import location_units, segment_events, source_paths
from swe_verified_claude4_traj.scripts import pre12_recompute as pre12


OUT = ROOT / "RQ1/data/rq1_2/mechanisms/preloop_trigger_mechanisms.csv"
TERMINAL_OUT = ROOT / "RQ1/data/rq1_2/mechanisms/preloop_terminal_mechanisms.csv"
TERMINAL_SUMMARY_OUT = ROOT / "RQ1/data/rq1_2/mechanisms/preloop_terminal_mechanism_summary.csv"
TRAJECTORY_INDEX = ROOT / "pre/pre-12/dataset/pre12_trajectories.csv"

REVISION_RE = re.compile(
    r"\b(?:actually|instead|rather than|root cause|real (?:issue|problem)|"
    r"this (?:means|suggests|indicates)|the (?:issue|problem|bug) is|"
    r"wrong (?:assumption|hypothesis)|new hypothesis|need to reconsider)\b",
    re.IGNORECASE,
)

RELATION_RE = re.compile(
    r"\b(?:caller|callee|call chain|call site|usage|references?|definition|"
    r"subclass|override|dispatch|backend|implementation|import|inherit)\b",
    re.IGNORECASE,
)


def has_run(events: list[dict[str, object]]) -> bool:
    return any(event.get("action") == "Run" or event.get("executes") for event in events)


def has_revision_reason(events: list[dict[str, object]]) -> bool:
    return any(
        event.get("action") == "Reason" and REVISION_RE.search(str(event.get("text", "")))
        for event in events
    )


def has_relation_search(events: list[dict[str, object]]) -> bool:
    return any(
        event.get("action") == "Search" and RELATION_RE.search(str(event.get("text", "")))
        for event in events
    )


def mechanism(
    fr_events: list[dict[str, object]],
    fl_events: list[dict[str, object]],
    new_paths: set[str],
    new_units: set[str],
) -> str:
    # Priority follows the observable source of the new cycle.  A runtime
    # probe is a stronger trigger than textual reasoning or static browsing.
    if has_run(fr_events):
        return "runtime_feedback"
    if has_revision_reason(fr_events + fl_events):
        return "hypothesis_revision"
    if new_paths and has_relation_search(fl_events):
        return "dependency_tracing"
    if new_paths:
        return "scope_expansion"
    if new_units:
        return "within_target_check"
    return "repeated_inspection"


def terminal_mechanism(
    fr_events: list[dict[str, object]],
    fl_events: list[dict[str, object]],
    seen_paths: set[str],
) -> str:
    """Classify the final cycle while preserving execution order."""
    combined = fr_events + fl_events
    run_indices = [
        index
        for index, event in enumerate(combined)
        if event.get("action") == "Run" or event.get("executes")
    ]
    if run_indices:
        after_run = [
            event
            for event in combined[max(run_indices) + 1 :]
            if event.get("is_source_path") and event.get("action") in {"Read", "Search"}
        ]
        if not after_run:
            return "runtime_feedback_without_relocalization"
        return (
            "runtime_feedback_new_candidate"
            if source_paths(after_run) - seen_paths
            else "runtime_feedback_previous_candidate"
        )
    return (
        "existing_evidence_new_candidate"
        if source_paths(fl_events) - seen_paths
        else "existing_evidence_previous_candidate"
    )


def band(k: int) -> str:
    if k == 1:
        return "1"
    if k == 2:
        return "2"
    if k <= 4:
        return "3-4"
    return "5+"


def main() -> None:
    refs = pre12.load_reference(pre12.ROOT, OUT.parent)
    with TRAJECTORY_INDEX.open(newline="", encoding="utf-8") as handle:
        complete = {
            (row["agent"], row["instance_id"])
            for row in csv.DictReader(handle)
            if row["complete_repair"] == "1"
        }
    rows: list[dict[str, object]] = []
    terminal_rows: list[dict[str, object]] = []
    for agent, instance_id, resolved, events, segments in pre12.load_all(pre12.ROOT, refs):
        if (agent, instance_id) not in complete:
            continue
        first_pc = next(
            (index for index, segment in enumerate(segments) if segment["subtask_code"] == "PC"),
            len(segments),
        )
        pairs = [
            (left, right)
            for left, right in zip(segments[:first_pc], segments[1:first_pc])
            if left["subtask_code"] == "FR" and right["subtask_code"] == "FL"
        ]
        seen_paths: set[str] = set()
        seen_units: set[str] = set()
        final_mechanism = ""
        for pair_index, (fr, fl) in enumerate(pairs, start=1):
            fr_events = segment_events(events, fr)
            fl_events = segment_events(events, fl)
            paths = source_paths(fl_events)
            units = location_units(fl_events)
            new_paths = paths - seen_paths
            new_units = units - seen_units
            final_mechanism = terminal_mechanism(fr_events, fl_events, seen_paths)
            if pair_index > 1:
                rows.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "resolved": int(resolved),
                        "loop_count": len(pairs),
                        "loop_band": band(len(pairs)),
                        "cycle_index": pair_index - 1,
                        "mechanism": mechanism(fr_events, fl_events, new_paths, new_units),
                        "has_runtime_feedback": int(has_run(fr_events)),
                        "has_hypothesis_revision": int(has_revision_reason(fr_events + fl_events)),
                        "has_relation_search": int(has_relation_search(fl_events)),
                        "new_target_count": len(new_paths),
                        "new_region_count": len(new_units),
                        "target_count": len(paths),
                    }
                )
            seen_paths.update(paths)
            seen_units.update(units)

        if pairs:
            terminal_rows.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": int(resolved),
                    "loop_count": len(pairs),
                    "loop_band": band(len(pairs)),
                    "terminal_mechanism": final_mechanism,
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with TERMINAL_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(terminal_rows[0]))
        writer.writeheader()
        writer.writerows(terminal_rows)
    terminal_summary: list[dict[str, object]] = []
    mechanisms = sorted({str(row["terminal_mechanism"]) for row in terminal_rows})
    for group in ("total", "lingxi", "moatless", "openhands"):
        group_rows = [
            row for row in terminal_rows if group == "total" or row["agent"] == group
        ]
        for name in mechanisms:
            selected = [row for row in group_rows if row["terminal_mechanism"] == name]
            terminal_summary.append(
                {
                    "group": group,
                    "terminal_mechanism": name,
                    "n": len(selected),
                    "share": round(len(selected) / len(group_rows), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    ),
                }
            )
    with TERMINAL_SUMMARY_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(terminal_summary[0]))
        writer.writeheader()
        writer.writerows(terminal_summary)

    for dimension in ("loop_band", "agent"):
        grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            grouped[(str(row[dimension]), str(row["mechanism"]))].append(row)
        print(f"\nBY {dimension.upper()}")
        for key, selected in sorted(grouped.items()):
            rate = sum(int(row["resolved"]) for row in selected) / len(selected)
            print(key[0], key[1], len(selected), f"{rate:.3f}")

    print(f"\nWrote {len(rows)} repeated-cycle events to {OUT}")
    print(f"Wrote {len(terminal_rows)} terminal-cycle records to {TERMINAL_OUT}")
    print(f"Wrote terminal-cycle summary to {TERMINAL_SUMMARY_OUT}")


if __name__ == "__main__":
    main()
