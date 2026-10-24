#!/usr/bin/env python3
"""Build traceable mechanism evidence for RQ1.2 pathway analysis.

This script does not redefine the Pre-12 taxonomy. It reuses the formal
event/subtask parser, then records what changes across each FR -> FL and
PV -> PR transition so that pathway explanations can be checked against the
raw trajectories.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RQ1 import rq1_2_task_fit_analysis as task_fit
from swe_verified_claude4_traj.scripts import pre12_recompute as pre12


OUT_DIR = Path(os.environ.get("RQ12_MECHANISM_OUT", ROOT / "RQ1/data/rq1_2/mechanisms"))

CLASS_NAMES = {
    "atomic_local": "single_file_single_site",
    "multisite_single_file": "single_file_multiple_sites",
    "intra_component_multifile": "multiple_files_one_module",
    "cross_component_coordination": "multiple_modules",
}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value: str, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def segment_events(events: list[dict[str, object]], segment: dict[str, object]) -> list[dict[str, object]]:
    start = int(segment["start_event"])
    end = int(segment["end_event"])
    return events[start : end + 1]


def source_paths(events: list[dict[str, object]]) -> set[str]:
    return {
        pre12.norm_path(str(event.get("path", "")))
        for event in events
        if event.get("path")
        and event.get("is_source_path")
        and not event.get("is_diagnostic_path")
    }


def product_edit_paths(events: list[dict[str, object]]) -> set[str]:
    return {
        pre12.norm_path(str(event.get("path", "")))
        for event in events
        if event.get("path") and pre12.is_patch_edit(event)
    }


def location_units(events: list[dict[str, object]]) -> set[str]:
    """Return path-plus-region units from observable source reads."""
    units: set[str] = set()
    range_pattern = re.compile(
        r"(?:view_range['\"]?\s*[:=]\s*\[|\blines?\s+)(\d+)\s*[,\-]\s*(\d+)",
        re.IGNORECASE,
    )
    for event in events:
        if not event.get("is_source_path") or not event.get("path"):
            continue
        path = pre12.norm_path(str(event["path"]))
        matches = range_pattern.findall(str(event.get("text", "")))
        if not matches:
            units.add(f"{path}:*")
            continue
        for start, end in matches:
            first_bucket = int(start) // 50
            last_bucket = int(end) // 50
            for bucket in range(first_bucket, last_bucket + 1):
                units.add(f"{path}:{bucket}")
    return units


def normalized_edit_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def overlaps_edit_region(left: str, right: str) -> bool:
    if len(left) < 30 or len(right) < 30:
        return False
    return left in right or right in left


def patch_revision_mechanism(
    edit_events: list[dict[str, object]],
    touched_paths: set[str],
    history: dict[str, list[tuple[str, str]]],
) -> str:
    edits = [event for event in edit_events if pre12.is_patch_edit(event)]
    if not edits:
        return "no_observable_source_edit"

    new_file = False
    same_hunk = False
    rollback = False
    for event in edits:
        path = pre12.norm_path(str(event.get("path", "")))
        if path not in touched_paths:
            new_file = True
        old = normalized_edit_text(event.get("old_str"))
        new = normalized_edit_text(event.get("new_str"))
        for previous_old, previous_new in history.get(path, []):
            if old and previous_new and overlaps_edit_region(old, previous_new):
                same_hunk = True
            if (
                old
                and new
                and previous_old
                and previous_new
                and overlaps_edit_region(old, previous_new)
                and overlaps_edit_region(new, previous_old)
            ):
                rollback = True

    if rollback:
        return "rollback_or_replacement"
    if new_file:
        return "new_file_responsibility_shift"
    if same_hunk:
        return "same_hunk_rework"
    return "same_file_new_hunk"


def joined_text(events: list[dict[str, object]], limit: int = 700) -> str:
    return clean_text(" ".join(str(event.get("text", "")) for event in events), limit)


def run_outcomes(events: list[dict[str, object]]) -> str:
    values = [str(event.get("outcome", "")).strip() for event in events if str(event.get("outcome", "")).strip()]
    return ";".join(values)


def reproduction_mode(events: list[dict[str, object]]) -> str:
    if any(event.get("action") == "Run" or event.get("executes") for event in events):
        return "executed_failure_probe"
    if any(event.get("is_diagnostic_artifact") for event in events):
        return "diagnostic_artifact"
    if any(event.get("action") in {"Read", "Search"} for event in events):
        return "failure_evidence_inspection"
    return "reasoning_only"


def relative_k_band(agent: str, k: int) -> str:
    # Agent-specific cut points are fixed from the complete-trajectory quartiles:
    # Lingxi Q1/Q3 = 6/9; Moatless = 1/3; OpenHands = 2/3.
    if agent == "lingxi":
        return "low" if k <= 6 else "typical" if k <= 9 else "high"
    if agent == "moatless":
        return "low" if k <= 1 else "typical" if k <= 3 else "high"
    return "low" if k <= 1 else "typical" if k <= 3 else "high"


def preloop_rows(
    agent: str,
    instance_id: str,
    resolved: bool,
    events: list[dict[str, object]],
    segments: list[dict[str, object]],
    ref: dict[str, object],
    task_class: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    first_pc = next((index for index, segment in enumerate(segments) if segment["subtask_code"] == "PC"), len(segments))
    before_patch = segments[:first_pc]
    pairs = [
        (left, right)
        for left, right in zip(before_patch, before_patch[1:])
        if left["subtask_code"] == "FR" and right["subtask_code"] == "FL"
    ]
    reference_paths = {
        pre12.norm_path(path)
        for path in ref.get("patch_files", set())
        if pre12.is_source_like(path, ref) and not pre12.is_test_path(path)
    }
    seen_targets: set[str] = set()
    seen_location_units: set[str] = set()
    seen_reference_targets: set[str] = set()
    rows: list[dict[str, object]] = []
    for pair_index, (fr, fl) in enumerate(pairs, start=1):
        fr_events = segment_events(events, fr)
        fl_events = segment_events(events, fl)
        targets = source_paths(fl_events)
        units = location_units(fl_events)
        new_targets = targets - seen_targets
        new_units = units - seen_location_units
        reference_hits = targets & reference_paths
        new_reference_hits = reference_hits - seen_reference_targets
        if new_reference_hits and not seen_reference_targets:
            progress = "first_reference_target"
        elif new_reference_hits:
            progress = "additional_reference_target"
        elif reference_hits:
            progress = "reference_target_confirmation"
        else:
            progress = "no_reference_target_gain"
        rows.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                "task_class": task_class,
                "task_class_readable": CLASS_NAMES[task_class],
                "k_total": len(pairs),
                "k_band": relative_k_band(agent, len(pairs)),
                "pair_index": pair_index,
                "fr_outcome": fr["local_outcome"],
                "fl_outcome": fl["local_outcome"],
                "fr_mode": reproduction_mode(fr_events),
                "fr_has_read": int(any(event.get("action") == "Read" for event in fr_events)),
                "fr_has_search": int(any(event.get("action") == "Search" for event in fr_events)),
                "fr_run_outcomes": run_outcomes(fr_events),
                "fr_blocked": int(any(event.get("blocked") for event in fr_events)),
                "fl_has_read": int(any(event.get("action") == "Read" for event in fl_events)),
                "fl_has_search": int(any(event.get("action") == "Search" for event in fl_events)),
                "fl_progress": progress,
                "fl_paths": ";".join(sorted(targets)),
                "new_target_paths": ";".join(sorted(new_targets)),
                "fl_location_units": ";".join(sorted(units)),
                "new_location_units": ";".join(sorted(new_units)),
                "reference_hits": ";".join(sorted(reference_hits)),
                "new_reference_hits": ";".join(sorted(new_reference_hits)),
                "fr_evidence": joined_text(fr_events),
                "fl_evidence": joined_text(fl_events),
            }
        )
        seen_targets.update(targets)
        seen_location_units.update(units)
        seen_reference_targets.update(reference_hits)

    counts = Counter(row["fl_progress"] for row in rows)
    modes = Counter(row["fr_mode"] for row in rows)
    summary = {
        "agent": agent,
        "instance_id": instance_id,
        "resolved": int(resolved),
        "task_class": task_class,
        "task_class_readable": CLASS_NAMES[task_class],
        "k": len(pairs),
        "k_band": relative_k_band(agent, len(pairs)),
        "executed_probe_pairs": modes["executed_failure_probe"],
        "inspection_pairs": modes["failure_evidence_inspection"],
        "reasoning_only_pairs": modes["reasoning_only"],
        "first_reference_target_pairs": counts["first_reference_target"],
        "additional_reference_target_pairs": counts["additional_reference_target"],
        "reference_target_confirmation_pairs": counts["reference_target_confirmation"],
        "no_reference_target_gain_pairs": counts["no_reference_target_gain"],
        "unique_localization_paths": len(seen_targets),
        "reference_paths_seen": len(seen_reference_targets),
        "reference_path_count": len(reference_paths),
    }
    return rows, summary


def postloop_rows(
    agent: str,
    instance_id: str,
    resolved: bool,
    events: list[dict[str, object]],
    segments: list[dict[str, object]],
    ref: dict[str, object],
    task_class: str,
) -> list[dict[str, object]]:
    reference_paths = {
        pre12.norm_path(path)
        for path in ref.get("patch_files", set())
        if pre12.is_source_like(path, ref) and not pre12.is_test_path(path)
    }
    touched: set[str] = set()
    edit_history: dict[str, list[tuple[str, str]]] = defaultdict(list)
    rows: list[dict[str, object]] = []
    loop_index = 0
    for index, segment in enumerate(segments):
        current_events = segment_events(events, segment)
        if segment["subtask_code"] in {"PC", "PR"}:
            touched.update(product_edit_paths(current_events))
            for event in current_events:
                if not pre12.is_patch_edit(event) or not event.get("path"):
                    continue
                path = pre12.norm_path(str(event["path"]))
                edit_history[path].append(
                    (
                        normalized_edit_text(event.get("old_str")),
                        normalized_edit_text(event.get("new_str")),
                    )
                )
        if index + 1 >= len(segments):
            continue
        refinement = segments[index + 1]
        if segment["subtask_code"] != "PV" or refinement["subtask_code"] != "PR":
            continue
        loop_index += 1
        pv_events = current_events
        pr_events = segment_events(events, refinement)
        before = set(touched)
        edits = product_edit_paths(pr_events)
        revision_mechanism = patch_revision_mechanism(pr_events, before, edit_history)
        new_reference_paths = (edits & reference_paths) - before
        if loop_index == 1 and new_reference_paths:
            mechanism = "first_reference_scope_expansion"
        elif loop_index == 1:
            mechanism = "first_same_scope_revision"
        elif new_reference_paths:
            mechanism = "repeated_reference_scope_expansion"
        else:
            mechanism = "repeated_same_scope_revision"
        touched.update(edits)
        rows.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                "task_class": task_class,
                "task_class_readable": CLASS_NAMES[task_class],
                "loop_index": loop_index,
                "pv_outcome": segment["local_outcome"],
                "pv_run_outcomes": run_outcomes(pv_events),
                "pv_has_run": int(
                    any(event.get("action") == "Run" or event.get("executes") for event in pv_events)
                ),
                "pv_blocked": int(any(event.get("blocked") for event in pv_events)),
                "pv_has_read_or_search": int(
                    any(event.get("action") in {"Read", "Search"} for event in pv_events)
                ),
                "pr_outcome": refinement["local_outcome"],
                "mechanism": mechanism,
                "revision_mechanism": revision_mechanism,
                "edit_paths": ";".join(sorted(edits)),
                "new_reference_paths": ";".join(sorted(new_reference_paths)),
                "reference_paths_touched_before": ";".join(sorted(before & reference_paths)),
                "reference_paths_touched_after": ";".join(sorted(touched & reference_paths)),
                "reference_path_count": len(reference_paths),
                "pv_evidence": joined_text(pv_events),
                "pr_evidence": joined_text(pr_events),
            }
        )
    for row in rows:
        row["r_total"] = len(rows)
    return rows


def print_summary(pre_summaries: list[dict[str, object]], post_rows: list[dict[str, object]]) -> None:
    print("PRE-PATCH K BY AGENT AND TASK CLASS")
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in pre_summaries:
        grouped[(str(row["agent"]), str(row["task_class_readable"]))].append(row)
    for key in sorted(grouped):
        rows = grouped[key]
        bands = Counter(str(row["k_band"]) for row in rows)
        mean_k = sum(int(row["k"]) for row in rows) / len(rows)
        informative = sum(
            int(row["executed_probe_pairs"])
            + int(row["first_reference_target_pairs"])
            + int(row["additional_reference_target_pairs"])
            for row in rows
        )
        pairs = sum(int(row["k"]) for row in rows)
        print(
            key[0],
            key[1],
            f"n={len(rows)}",
            f"mean_k={mean_k:.2f}",
            f"low/typical/high={bands['low']}/{bands['typical']}/{bands['high']}",
            f"observable_progress={informative / pairs:.3f}" if pairs else "observable_progress=NA",
        )

    print("\nPOST-PATCH REVISION MECHANISMS")
    post_grouped: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in post_rows:
        post_grouped[(str(row["task_class_readable"]), "resolved" if row["resolved"] else "unresolved")][
            str(row["mechanism"])
        ] += 1
    for key in sorted(post_grouped):
        print(key[0], key[1], dict(post_grouped[key]))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    refs = pre12.load_reference(pre12.ROOT, OUT_DIR)
    tasks = task_fit.load_tasks()
    task_class_by_id = {
        str(task["instance_id"]): task_fit.candidate_task_class(task_fit.bin_task_features(task)) for task in tasks
    }

    pre_pairs: list[dict[str, object]] = []
    pre_summaries: list[dict[str, object]] = []
    post_pairs: list[dict[str, object]] = []
    for agent, instance_id, resolved, events, segments in pre12.load_all(pre12.ROOT, refs):
        task_class = task_class_by_id[instance_id]
        pairs, summary = preloop_rows(agent, instance_id, resolved, events, segments, refs[instance_id], task_class)
        pre_pairs.extend(pairs)
        pre_summaries.append(summary)
        post_pairs.extend(postloop_rows(agent, instance_id, resolved, events, segments, refs[instance_id], task_class))

    write_csv(OUT_DIR / "preloop_pairs.csv", pre_pairs)
    write_csv(OUT_DIR / "preloop_trajectory_summary.csv", pre_summaries)
    write_csv(OUT_DIR / "postloop_pairs.csv", post_pairs)
    print_summary(pre_summaries, post_pairs)
    print(f"\nWrote mechanism evidence to {OUT_DIR}")


if __name__ == "__main__":
    main()
