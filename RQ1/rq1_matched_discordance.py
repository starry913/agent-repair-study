#!/usr/bin/env python3
"""Within-instance comparison of trajectories sharing the same local outcome."""

import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OUT_DIR = ROOT / "RQ1" / "discordance"
sys.path.insert(0, str(TRAJ_ROOT))
sys.path.insert(0, str(ROOT / "RQ1"))

from scripts import pre12_recompute as pre  # noqa: E402
import rq1_discordance_mechanisms as mech  # noqa: E402


FEATURES = (
    "segment_reference_path_coverage",
    "segment_oracle_hunk_token_hits",
    "segment_reference_file_coverage",
    "segment_positive_direction",
    "segment_opposing_direction",
    "segment_run_count",
    "segment_exact_target_fail",
    "segment_related_fail",
    "segment_any_fail",
    "trajectory_reference_file_coverage",
    "trajectory_positive_direction",
    "trajectory_opposing_direction",
    "later_reference_file_coverage",
    "later_positive_direction",
    "later_opposing_direction",
    "last_target_validation_score",
    "pv_pr_loops",
)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def target_validation_score(events, ref):
    state = mech.last_decisive(events, ref, target_only=True)
    return {"fail": -1, "unknown": 0, "pass": 1}[state]


def feature_row(agent, instance_id, resolved, events, segments, ref, code):
    selected = mech.select_anchor(segments, code)
    if not selected:
        return None
    _, segment = selected
    segment_events = events[segment["start_event"] : segment["end_event"] + 1]
    later_events = events[segment["end_event"] + 1 :]
    segment_paths = mech.path_profile(segment_events, ref)
    segment_edits = mech.edit_profile(segment_events, ref)
    segment_runs = mech.run_profile(segment_events, ref)
    trajectory_edits = mech.edit_profile(events, ref)
    later_edits = mech.edit_profile(later_events, ref)
    codes = [item["subtask_code"] for item in segments]
    loops = sum(left == "PV" and right == "PR" for left, right in zip(codes, codes[1:]))
    return {
        "agent": agent,
        "instance_id": instance_id,
        "resolved": int(resolved),
        "subtask_code": code,
        "local_outcome": segment["local_outcome"],
        "segment_reference_path_coverage": segment_paths["reference_path_coverage"],
        "segment_oracle_hunk_token_hits": segment_paths["oracle_hunk_token_hits"],
        "segment_reference_file_coverage": segment_edits["reference_file_coverage"],
        "segment_positive_direction": segment_edits["positive_direction"],
        "segment_opposing_direction": segment_edits["opposing_direction"],
        "segment_run_count": segment_runs["run_count"],
        "segment_exact_target_fail": segment_runs["exact_target_fail"],
        "segment_related_fail": segment_runs["related_fail"],
        "segment_any_fail": segment_runs["any_fail"],
        "trajectory_reference_file_coverage": trajectory_edits["reference_file_coverage"],
        "trajectory_positive_direction": trajectory_edits["positive_direction"],
        "trajectory_opposing_direction": trajectory_edits["opposing_direction"],
        "later_reference_file_coverage": later_edits["reference_file_coverage"],
        "later_positive_direction": later_edits["positive_direction"],
        "later_opposing_direction": later_edits["opposing_direction"],
        "last_target_validation_score": target_validation_score(events, ref),
        "pv_pr_loops": loops,
    }


def binomial_two_sided(positive, negative):
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(positive, negative) + 1)) / (2**n)
    return min(1.0, 2 * tail)


def summarize(rows):
    grouped = defaultdict(list)
    by_cell = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row["subtask_code"], row["local_outcome"])
        by_cell[key][row["instance_id"]].append(row)

    matched_rows = []
    for (code, outcome), instances in by_cell.items():
        for instance_id, items in instances.items():
            resolved = [item for item in items if item["resolved"]]
            unresolved = [item for item in items if not item["resolved"]]
            if not resolved or not unresolved:
                continue
            base = {
                "subtask_code": code,
                "local_outcome": outcome,
                "instance_id": instance_id,
                "resolved_agents": ";".join(sorted(item["agent"] for item in resolved)),
                "unresolved_agents": ";".join(sorted(item["agent"] for item in unresolved)),
            }
            for feature in FEATURES:
                resolved_mean = statistics.mean(float(item[feature]) for item in resolved)
                unresolved_mean = statistics.mean(float(item[feature]) for item in unresolved)
                matched_rows.append(
                    {
                        **base,
                        "feature": feature,
                        "resolved_mean": f"{resolved_mean:.6f}",
                        "unresolved_mean": f"{unresolved_mean:.6f}",
                        "delta": f"{resolved_mean - unresolved_mean:.6f}",
                    }
                )
                grouped[(code, outcome, feature)].append(resolved_mean - unresolved_mean)

    summary = []
    for (code, outcome, feature), deltas in sorted(grouped.items()):
        positive = sum(delta > 1e-9 for delta in deltas)
        negative = sum(delta < -1e-9 for delta in deltas)
        ties = len(deltas) - positive - negative
        summary.append(
            {
                "subtask_code": code,
                "local_outcome": outcome,
                "feature": feature,
                "matched_instances": len(deltas),
                "mean_delta": f"{statistics.mean(deltas):.4f}",
                "median_delta": f"{statistics.median(deltas):.4f}",
                "resolved_higher": positive,
                "unresolved_higher": negative,
                "ties": ties,
                "sign_test_p": f"{binomial_two_sided(positive, negative):.4f}",
            }
        )
    return matched_rows, summary


def main():
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_matched"))
    rows = []
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        for code in mech.ANCHOR:
            row = feature_row(
                agent, instance_id, resolved, events, segments, refs[instance_id], code
            )
            if row:
                rows.append(row)
    matched_rows, summary = summarize(rows)
    write_csv(OUT_DIR / "matched_instance_differences.csv", matched_rows)
    write_csv(OUT_DIR / "matched_instance_summary.csv", summary)
    print(f"matched_instance_feature_rows={len(matched_rows)}")
    for row in summary:
        if row["sign_test_p"] != "1.0000" and float(row["sign_test_p"]) < 0.05:
            print(
                f"{row['subtask_code']}{row['local_outcome']} "
                f"{row['feature']}: delta={row['mean_delta']}, "
                f"n={row['matched_instances']}, p={row['sign_test_p']}"
            )


if __name__ == "__main__":
    main()
