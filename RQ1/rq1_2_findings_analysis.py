#!/usr/bin/env python3
"""Generate the final RQ1.2 finding tables from the complete Pre-12 data."""

from __future__ import annotations

import csv
import math
import random
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "RQ1/data/rq1_2"
TASKS = BASE / "task_fit/trajectories_enriched.csv"
PRE_PAIRS = BASE / "mechanisms/preloop_pairs.csv"
POST_PAIRS = BASE / "mechanisms/postloop_pairs.csv"
OUT = BASE / "findings"

CLASS_ORDER = (
    "atomic_local",
    "multisite_single_file",
    "intra_component_multifile",
    "cross_component_coordination",
)
CLASS_NAMES = {
    "atomic_local": "单文件单点修复",
    "multisite_single_file": "单文件多点修复",
    "intra_component_multifile": "模块内多文件修复",
    "cross_component_coordination": "跨模块多文件修复",
}
PRE_MECHANISMS = (
    "first_reference_target",
    "additional_reference_target",
    "reference_target_confirmation",
    "no_reference_target_gain",
)
POST_MECHANISMS = (
    "first_reference_scope_expansion",
    "first_same_scope_revision",
    "repeated_reference_scope_expansion",
    "repeated_same_scope_revision",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def rate(rows: list[dict[str, str]]) -> float:
    return sum(int(row["resolved"]) for row in rows) / len(rows)


def pre_band(value: int) -> str:
    return "0-1" if value <= 1 else "2-3" if value <= 3 else "4-5" if value <= 5 else "6+"


def post_band(value: int) -> str:
    return "0" if value == 0 else "1" if value == 1 else "2" if value == 2 else "3+"


def audit_task_class(row: dict[str, str], variant: str) -> str:
    files = int(row["source_file_count"])
    parents = int(row["source_parent_count"])
    hunks = int(row["hunk_count"])
    tests = int(row["fail_to_pass_count"])
    test_files = int(row["fail_test_file_count"])
    loc = int(row["changed_loc"])
    if variant == "pre12_original":
        if files > 1 and parents > 1:
            return "cross"
        if files > 1:
            return "within"
        return "constraint_rich" if hunks > 1 or tests > 1 or test_files > 1 else "atomic"
    if variant == "reference_topology":
        return row["candidate_class"]
    if variant == "obligation_thresholds":
        obligations = max(hunks, tests, test_files)
        if files > 1:
            return "distributed"
        if obligations >= 3 or loc > 30:
            return "dense"
        if obligations == 2 or loc > 10:
            return "extended"
        return "atomic"
    if variant == "file_count_only":
        return "cross" if parents > 1 else "3plus" if files > 2 else "two" if files == 2 else "one"
    raise ValueError(variant)


def eta_squared(rows: list[dict[str, str]], variant: str, feature: str) -> float:
    values = [int(row[feature]) for row in rows]
    mean = sum(values) / len(values)
    total = sum((value - mean) ** 2 for value in values)
    grouped: dict[str, list[int]] = defaultdict(list)
    for row, value in zip(rows, values):
        grouped[audit_task_class(row, variant)].append(value)
    between = sum(len(group) * (sum(group) / len(group) - mean) ** 2 for group in grouped.values())
    return between / total


def cramers_v(rows: list[dict[str, str]], category) -> float:
    left = sorted({row["task_class"] for row in rows})
    right = sorted({category(row) for row in rows})
    observed = [[sum(row["task_class"] == x and category(row) == y for row in rows) for y in right] for x in left]
    row_totals = [sum(row) for row in observed]
    col_totals = [sum(observed[i][j] for i in range(len(left))) for j in range(len(right))]
    total = sum(row_totals)
    chi2 = 0.0
    for i in range(len(left)):
        for j in range(len(right)):
            expected = row_totals[i] * col_totals[j] / total
            chi2 += (observed[i][j] - expected) ** 2 / expected
    return math.sqrt((chi2 / total) / min(len(left) - 1, len(right) - 1))


def bootstrap_ci(values: list[float], seed: int = 20260731) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    for _ in range(10_000):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return means[249], means[9749]


def matched_contrast(
    trajectories: list[dict[str, str]], task_class: str, phase: str, left: str, right: str
) -> dict[str, object]:
    band_fn = pre_band if phase == "pre" else post_band
    loop_key = f"{phase}_loops"
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in trajectories:
        if row["candidate_class"] == task_class:
            grouped[row["instance_id"]].append(row)
    differences = []
    for rows in grouped.values():
        left_y = [int(row["resolved"]) for row in rows if band_fn(int(row[loop_key])) == left]
        right_y = [int(row["resolved"]) for row in rows if band_fn(int(row[loop_key])) == right]
        if left_y and right_y:
            differences.append(sum(left_y) / len(left_y) - sum(right_y) / len(right_y))
    low, high = bootstrap_ci(differences)
    return {
        "phase": phase,
        "task_class": task_class,
        "task_type": CLASS_NAMES[task_class],
        "contrast": f"{left} - {right}",
        "matched_instances": len(differences),
        "delta_rr": round(sum(differences) / len(differences), 3) if differences else "",
        "ci95_low": round(low, 3) if differences else "",
        "ci95_high": round(high, 3) if differences else "",
    }


def main() -> None:
    trajectories = read_csv(TASKS)
    trajectory_by_key = {(row["agent"], row["instance_id"]): row for row in trajectories}

    taxonomy_audit = []
    for variant in ("pre12_original", "reference_topology", "obligation_thresholds", "file_count_only"):
        scores = [eta_squared(trajectories, variant, feature) for feature in ("distinct_subtask_types", "pre_loops", "post_loops")]
        counts = Counter(audit_task_class(row, variant) for row in trajectories)
        taxonomy_audit.append(
            {
                "variant": variant,
                "min_group_n": min(counts.values()),
                "eta2_distinct": round(scores[0], 4),
                "eta2_pre_loops": round(scores[1], 4),
                "eta2_post_loops": round(scores[2], 4),
                "mean_eta2": round(sum(scores) / len(scores), 4),
                "selected": int(variant == "reference_topology"),
            }
        )
    write_csv(OUT / "task_taxonomy_audit.csv", taxonomy_audit)

    distinct_rows = []
    for task_class in CLASS_ORDER:
        rows = [row for row in trajectories if row["candidate_class"] == task_class]
        counts = Counter(int(row["distinct_subtask_types"]) for row in rows)
        distinct_rows.append(
            {
                "task_class": task_class,
                "task_type": CLASS_NAMES[task_class],
                "n": len(rows),
                "D4_share": round(counts[4] / len(rows), 4),
                "D5_share": round(counts[5] / len(rows), 4),
                "D6_share": round(counts[6] / len(rows), 4),
                "repeated_fr_fl_share": round(
                    sum(int(row["pre_loops"]) >= 2 for row in rows) / len(rows),
                    4,
                ),
                "repeated_pv_pr_share": round(
                    sum(int(row["post_loops"]) >= 2 for row in rows) / len(rows),
                    4,
                ),
            }
        )
    write_csv(OUT / "distinct_by_task_type.csv", distinct_rows)

    window_rows = []
    for phase, bands, band_fn in (
        ("pre", ("0-1", "2-3", "4-5", "6+"), pre_band),
        ("post", ("0", "1", "2", "3+"), post_band),
    ):
        for task_class in CLASS_ORDER:
            for band in bands:
                rows = [
                    row
                    for row in trajectories
                    if row["candidate_class"] == task_class
                    and band_fn(int(row[f"{phase}_loops"])) == band
                ]
                window_rows.append(
                    {
                        "phase": phase,
                        "task_class": task_class,
                        "task_type": CLASS_NAMES[task_class],
                        "loop_band": band,
                        "n": len(rows),
                        "resolved_rate": round(rate(rows), 4),
                    }
                )
    write_csv(OUT / "loop_windows.csv", window_rows)

    mechanism_rows = []
    for phase, path, mechanism_key, mechanisms in (
        ("pre", PRE_PAIRS, "fl_progress", PRE_MECHANISMS),
        ("post", POST_PAIRS, "mechanism", POST_MECHANISMS),
    ):
        pairs = [
            row
            for row in read_csv(path)
            if (row["agent"], row["instance_id"]) in trajectory_by_key
        ]
        for task_class in CLASS_ORDER:
            class_pairs = [row for row in pairs if row["task_class"] == task_class]
            for mechanism in mechanisms:
                selected = [row for row in class_pairs if row[mechanism_key] == mechanism]
                keys = {
                    (row["agent"], row["instance_id"])
                    for row in selected
                    if (row["agent"], row["instance_id"]) in trajectory_by_key
                }
                associated = [trajectory_by_key[key] for key in keys]
                mechanism_rows.append(
                    {
                        "phase": phase,
                        "task_class": task_class,
                        "task_type": CLASS_NAMES[task_class],
                        "mechanism": mechanism,
                        "pair_n": len(selected),
                        "pair_share": round(len(selected) / len(class_pairs), 4) if class_pairs else "",
                        "trajectory_n": len(associated),
                        "associated_resolved_rate": round(rate(associated), 4) if associated else "",
                    }
                )
    write_csv(OUT / "loop_mechanisms.csv", mechanism_rows)

    complete_keys = set(trajectory_by_key)
    pre_audit = [row for row in read_csv(PRE_PAIRS) if (row["agent"], row["instance_id"]) in complete_keys]
    post_audit = [row for row in read_csv(POST_PAIRS) if (row["agent"], row["instance_id"]) in complete_keys]
    old_pre = lambda row: (
        "new_reference" if row["new_reference_hits"] else
        "new_candidate" if row["new_target_paths"] else
        "revisit" if row["fl_paths"] else "none"
    )
    old_post = lambda row: (
        "scope_expansion" if row["new_reference_paths"] else
        "same_scope" if row["pr_outcome"] == "+" and row["edit_paths"] else
        "off_oracle" if row["pr_outcome"] == "-" else "unclear"
    )
    mechanism_audit = [
        {"phase": "pre", "scheme": "original", "cramers_v": round(cramers_v(pre_audit, old_pre), 4), "uses_local_outcome": 0},
        {"phase": "pre", "scheme": "first_additional_confirmation_gain", "cramers_v": round(cramers_v(pre_audit, lambda row: row["fl_progress"]), 4), "uses_local_outcome": 0},
        {"phase": "post", "scheme": "original", "cramers_v": round(cramers_v(post_audit, old_post), 4), "uses_local_outcome": 1},
        {"phase": "post", "scheme": "first_repeated_x_scope", "cramers_v": round(cramers_v(post_audit, lambda row: row["mechanism"]), 4), "uses_local_outcome": 0},
    ]
    write_csv(OUT / "mechanism_separation_audit.csv", mechanism_audit)

    contrasts = [
        matched_contrast(trajectories, "atomic_local", "pre", "0-1", "2-3"),
        matched_contrast(trajectories, "atomic_local", "pre", "0-1", "6+"),
        matched_contrast(trajectories, "cross_component_coordination", "pre", "2-3", "0-1"),
        matched_contrast(trajectories, "cross_component_coordination", "pre", "4-5", "2-3"),
        matched_contrast(trajectories, "atomic_local", "post", "3+", "0"),
        matched_contrast(trajectories, "multisite_single_file", "post", "3+", "0"),
        matched_contrast(trajectories, "cross_component_coordination", "post", "3+", "0"),
        matched_contrast(trajectories, "cross_component_coordination", "post", "3+", "1"),
    ]
    write_csv(OUT / "matched_loop_contrasts.csv", contrasts)

    print(f"trajectories={len(trajectories)}")
    print(f"pre_pairs={sum((row['agent'], row['instance_id']) in complete_keys for row in read_csv(PRE_PAIRS))}")
    print(f"post_pairs={sum((row['agent'], row['instance_id']) in complete_keys for row in read_csv(POST_PAIRS))}")
    print(f"wrote={OUT}")


if __name__ == "__main__":
    main()
