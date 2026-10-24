#!/usr/bin/env python3
"""Analyze observable stopping signals for RQ1.2 repair loops."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "RQ1/data/rq1_2"
PRE_PAIRS = BASE / "mechanisms/preloop_pairs.csv"
PRE_SUMMARY = BASE / "mechanisms/preloop_trajectory_summary.csv"
POST_CASES = ROOT / "RQ1/audit/pr_validation_scope_cases.csv"
POST_PAIRS = BASE / "mechanisms/postloop_pairs.csv"
TRAJECTORIES = BASE / "task_fit/trajectories_enriched.csv"
OUT = BASE / "stopping"

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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize_binary(rows: list[dict[str, object]], field: str) -> tuple[int, float, float]:
    if not rows:
        return 0, 0.0, 0.0
    return (
        len(rows),
        sum(int(row[field]) for row in rows) / len(rows),
        sum(int(row["resolved"]) for row in rows) / len(rows),
    )


def pre_stagnation_opportunities(pre_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pre_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)

    opportunities: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["pair_index"]))
        streak = 0
        first_reached: set[int] = set()
        for index, row in enumerate(rows):
            streak = streak + 1 if not row["new_target_paths"] else 0
            for threshold in (1, 2, 3):
                if streak < threshold or threshold in first_reached:
                    continue
                first_reached.add(threshold)
                later = rows[index + 1 :]
                opportunities.append(
                    {
                        "agent": row["agent"],
                        "instance_id": row["instance_id"],
                        "task_class": row["task_class"],
                        "scope_class": (
                            "single_file"
                            if row["task_class"] in {"atomic_local", "multisite_single_file"}
                            else "multi_file"
                        ),
                        "threshold": threshold,
                        "future_new_target": int(any(item["new_target_paths"] for item in later)),
                        "future_new_reference_target": int(any(item["new_reference_hits"] for item in later)),
                        "resolved": int(row["resolved"]),
                    }
                )

    return opportunities


def aggregate_pre_stagnation(
    opportunities: list[dict[str, object]], group_field: str, groups: list[str]
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for group in groups:
        for threshold in (1, 2, 3):
            selected = [
                row
                for row in opportunities
                if row["threshold"] == threshold
                and (group == "total" or row[group_field] == group)
            ]
            n, future_rate, resolved_rate = summarize_binary(selected, "future_new_target")
            reference_rate = (
                sum(int(row["future_new_reference_target"]) for row in selected) / n if n else 0.0
            )
            output.append(
                {
                    "group": group,
                    "group_name": (
                        "总体"
                        if group == "total"
                        else CLASS_NAMES.get(
                            group,
                            {"single_file": "单文件", "multi_file": "多文件"}.get(
                                group, group.capitalize()
                            ),
                        )
                    ),
                    "consecutive_no_new_target": threshold,
                    "n": n,
                    "future_new_target_rate": round(future_rate, 4),
                    "future_new_reference_target_rate": round(reference_rate, 4),
                    "resolved_rate": round(resolved_rate, 4),
                }
            )
    return output


def pre_evidence_target_rows(pre_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for agent in ("total", "lingxi", "moatless", "openhands"):
        rows = [row for row in pre_pairs if agent == "total" or row["agent"] == agent]
        for evidence in ("executed", "not_executed"):
            for target in ("new_target", "revisited_target"):
                selected = [
                    row
                    for row in rows
                    if (row["fr_mode"] == "executed_failure_probe") == (evidence == "executed")
                    and bool(row["new_target_paths"]) == (target == "new_target")
                ]
                output.append(
                    {
                        "agent": agent,
                        "failure_evidence": evidence,
                        "localization_target": target,
                        "n": len(selected),
                        "share": round(len(selected) / len(rows), 4),
                        "resolved_rate": round(
                            sum(int(row["resolved"]) for row in selected) / len(selected), 4
                        )
                        if selected
                        else "",
                    }
                )
    return output


def executed_feedback_loop_rows(
    trajectories: list[dict[str, str]], pre_pairs: list[dict[str, str]]
) -> list[dict[str, object]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in pre_pairs:
        if row["fr_mode"] == "executed_failure_probe":
            counts[(row["agent"], row["instance_id"])] += 1
    output: list[dict[str, object]] = []
    for agent in ("total", "lingxi", "moatless", "openhands"):
        rows = [row for row in trajectories if agent == "total" or row["agent"] == agent]
        for band, predicate in (
            ("0", lambda value: value == 0),
            ("1", lambda value: value == 1),
            ("2", lambda value: value == 2),
            ("3+", lambda value: value >= 3),
        ):
            selected = [
                row
                for row in rows
                if predicate(counts[(row["agent"], row["instance_id"])])
            ]
            output.append(
                {
                    "agent": agent,
                    "executed_fr_fl_loops": band,
                    "n": len(selected),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def executed_feedback_matched_rows(
    trajectories: list[dict[str, str]], pre_pairs: list[dict[str, str]]
) -> list[dict[str, object]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in pre_pairs:
        if row["fr_mode"] == "executed_failure_probe":
            counts[(row["agent"], row["instance_id"])] += 1
    by_instance: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in trajectories:
        count = counts[(row["agent"], row["instance_id"])]
        band = "0" if count == 0 else "1" if count == 1 else "2+"
        by_instance[row["instance_id"]].append(
            {"band": band, "resolved": int(row["resolved"])}
        )
    output: list[dict[str, object]] = []
    for left, right in (("0", "1"), ("0", "2+"), ("1", "2+")):
        differences: list[float] = []
        for rows in by_instance.values():
            left_values = [int(row["resolved"]) for row in rows if row["band"] == left]
            right_values = [int(row["resolved"]) for row in rows if row["band"] == right]
            if left_values and right_values:
                differences.append(
                    sum(right_values) / len(right_values) - sum(left_values) / len(left_values)
                )
        output.append(
            {
                "contrast": f"{right} - {left}",
                "matched_instances": len(differences),
                "delta_resolved_rate": round(sum(differences) / len(differences), 4)
                if differences
                else "",
            }
        )
    return output


def validation_comparability_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    decisive = [
        row
        for row in cases
        if row["transition"] in {"fail-to-pass", "fail-to-fail", "pass-to-pass", "pass-to-fail"}
    ]
    output: list[dict[str, object]] = []
    for transition in ("fail-to-pass", "fail-to-fail", "pass-to-pass", "pass-to-fail"):
        for relation in (
            "same_scope",
            "expanded_scope",
            "narrowed_scope",
            "changed_scope",
            "scope_unknown",
        ):
            rows = [
                row
                for row in decisive
                if row["transition"] == transition and row["scope_relation"] == relation
            ]
            if not rows:
                continue
            output.append(
                {
                    "transition": transition,
                    "scope_relation": relation,
                    "n": len(rows),
                    "share_within_transition": round(
                        len(rows) / sum(item["transition"] == transition for item in decisive), 4
                    ),
                    "resolved_rate": round(sum(int(row["resolved"]) for row in rows) / len(rows), 4),
                }
            )
    return output


def validation_by_task_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    decisive = [
        row
        for row in cases
        if row["transition"] in {"fail-to-pass", "fail-to-fail", "pass-to-pass", "pass-to-fail"}
    ]
    output: list[dict[str, object]] = []
    for task_class in CLASS_ORDER:
        rows = [row for row in decisive if row["task_class"] == task_class]
        fail_to_pass = [row for row in rows if row["transition"] == "fail-to-pass"]
        output.append(
            {
                "task_class": task_class,
                "task_type": CLASS_NAMES[task_class],
                "decisive_comparisons": len(rows),
                "changed_scope_share": round(
                    sum(row["scope_relation"] == "changed_scope" for row in rows) / len(rows), 4
                ),
                "fail_to_pass_n": len(fail_to_pass),
                "fail_to_pass_changed_scope_share": round(
                    sum(row["scope_relation"] == "changed_scope" for row in fail_to_pass)
                    / len(fail_to_pass),
                    4,
                )
                if fail_to_pass
                else 0.0,
            }
        )
    return output


def post_scope_trajectory_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        if row["agent"] in {"moatless", "openhands"}:
            grouped[(row["agent"], row["instance_id"])].append(row)

    trajectories: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        decisive = [
            row
            for row in rows
            if row["transition"] in {"fail-to-pass", "fail-to-fail", "pass-to-pass", "pass-to-fail"}
        ]
        trajectories.append(
            {
                "task_class": rows[0]["task_class"],
                "loop_band": "1" if len(rows) == 1 else "2" if len(rows) == 2 else "3+",
                "resolved": int(rows[0]["resolved"]),
                "has_changed_scope": int(
                    any(row["scope_relation"] == "changed_scope" for row in decisive)
                ),
                "decisive_comparisons": len(decisive),
            }
        )

    output: list[dict[str, object]] = []
    for task_class in CLASS_ORDER:
        for band in ("1", "2", "3+"):
            rows = [
                row
                for row in trajectories
                if row["task_class"] == task_class and row["loop_band"] == band
            ]
            if not rows:
                continue
            output.append(
                {
                    "task_class": task_class,
                    "task_type": CLASS_NAMES[task_class],
                    "pv_pr_loops": band,
                    "n": len(rows),
                    "resolved_rate": round(sum(int(row["resolved"]) for row in rows) / len(rows), 4),
                    "validation_scope_switch_share": round(
                        sum(int(row["has_changed_scope"]) for row in rows) / len(rows), 4
                    ),
                    "decisive_evidence_share": round(
                        sum(int(row["decisive_comparisons"]) > 0 for row in rows) / len(rows), 4
                    ),
                }
            )
    return output


def post_stagnation_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        grouped[(row["agent"], row["instance_id"])].append(row)

    opportunities: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        streak = 0
        first_reached: set[int] = set()
        for index, row in enumerate(rows):
            comparable_stagnation = (
                row["scope_relation"] == "same_scope" and row["transition"] == "fail-to-fail"
            )
            streak = streak + 1 if comparable_stagnation else 0
            for threshold in (1, 2):
                if streak < threshold or threshold in first_reached:
                    continue
                first_reached.add(threshold)
                later = rows[index + 1 :]
                opportunities.append(
                    {
                        "threshold": threshold,
                        "future_same_scope_fail_to_pass": int(
                            any(
                                item["scope_relation"] == "same_scope"
                                and item["transition"] == "fail-to-pass"
                                for item in later
                            )
                        ),
                        "resolved": int(row["resolved"]),
                    }
                )

    output: list[dict[str, object]] = []
    for threshold in (1, 2):
        rows = [row for row in opportunities if row["threshold"] == threshold]
        n, future_rate, resolved_rate = summarize_binary(rows, "future_same_scope_fail_to_pass")
        output.append(
            {
                "consecutive_same_scope_fail_to_fail": threshold,
                "n": n,
                "future_same_scope_fail_to_pass_rate": round(future_rate, 4),
                "resolved_rate": round(resolved_rate, 4),
            }
        )
    return output


def post_trigger_rows(post_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for loop_band, predicate in (
        ("first", lambda value: value == 1),
        ("repeated", lambda value: value >= 2),
    ):
        rows = [row for row in post_pairs if predicate(int(row["loop_index"]))]
        for outcome in ("+", "-", "?"):
            selected = [row for row in rows if row["pv_outcome"] == outcome]
            output.append(
                {
                    "loop_position": loop_band,
                    "pv_outcome": outcome,
                    "n": len(selected),
                    "share": round(len(selected) / len(rows), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_trigger_evidence_rows(post_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for loop_band, predicate in (
        ("first", lambda value: value == 1),
        ("repeated", lambda value: value >= 2),
    ):
        rows = [row for row in post_pairs if predicate(int(row["loop_index"]))]
        for evidence in ("fail", "pass", "no_decisive_result"):
            selected = []
            for row in rows:
                outcomes = set(filter(None, row["pv_run_outcomes"].split(";")))
                category = (
                    "fail"
                    if "fail" in outcomes
                    else "pass"
                    if "pass" in outcomes
                    else "no_decisive_result"
                )
                if category == evidence:
                    selected.append(row)
            output.append(
                {
                    "loop_position": loop_band,
                    "trigger_evidence": evidence,
                    "n": len(selected),
                    "share": round(len(selected) / len(rows), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_evidence_chain_rows(
    cases: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        grouped[(row["agent"], row["instance_id"])].append(row)
    trajectories: list[dict[str, object]] = []
    decisive_transitions = {"fail-to-pass", "fail-to-fail", "pass-to-pass", "pass-to-fail"}
    for rows in grouped.values():
        anchored = sum(
            row["transition"] in decisive_transitions
            and row["scope_relation"] in {"same_scope", "expanded_scope"}
            for row in rows
        )
        coverage = anchored / len(rows)
        trajectories.append(
            {
                "agent": rows[0]["agent"],
                "instance_id": rows[0]["instance_id"],
                "loops": len(rows),
                "anchored_links": anchored,
                "loop_band": "1" if len(rows) == 1 else "2" if len(rows) == 2 else "3+",
                "evidence_chain": (
                    "none" if anchored == 0 else "partial" if coverage < 1 else "complete"
                ),
                "resolved": int(rows[0]["resolved"]),
            }
        )
    output: list[dict[str, object]] = []
    for loop_band in ("1", "2", "3+"):
        for evidence_chain in ("none", "partial", "complete"):
            rows = [
                row
                for row in trajectories
                if row["loop_band"] == loop_band and row["evidence_chain"] == evidence_chain
            ]
            if not rows:
                continue
            output.append(
                {
                    "pv_pr_loops": loop_band,
                    "anchored_validation_chain": evidence_chain,
                    "n": len(rows),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in rows) / len(rows), 4
                    ),
                }
            )
    cases_output = [
        {
            "agent": row["agent"],
            "instance_id": row["instance_id"],
            "pv_pr_loops": row["loops"],
            "anchored_links": row["anchored_links"],
            "anchored_validation_chain": row["evidence_chain"],
            "resolved": row["resolved"],
        }
        for row in trajectories
    ]
    return output, cases_output


def post_loop_type_depth_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    """Classify whole post-patch loops using observable validation behavior only."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    decisive = {"fail-to-pass", "fail-to-fail", "pass-to-fail", "pass-to-pass"}
    anchored_scopes = {"same_scope", "expanded_scope"}
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        anchored = [
            row
            for row in rows
            if row["transition"] in decisive and row["scope_relation"] in anchored_scopes
        ]
        shifted = [
            row
            for row in rows
            if row["transition"] in decisive and row["scope_relation"] not in anchored_scopes
        ]
        if any(row["transition"] == "fail-to-pass" for row in anchored):
            loop_type = "confirmed_recovery"
        elif anchored:
            loop_type = "comparable_without_recovery"
        elif shifted:
            loop_type = "shifted_validation"
        else:
            loop_type = "unclosed_feedback"
        records.append(
            {
                "agent": rows[0]["agent"],
                "instance_id": rows[0]["instance_id"],
                "loop_band": "1" if len(rows) == 1 else "2" if len(rows) == 2 else "3+",
                "loop_type": loop_type,
                "resolved": int(rows[0]["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    loop_types = (
        "confirmed_recovery",
        "comparable_without_recovery",
        "shifted_validation",
        "unclosed_feedback",
    )
    for band in ("1", "2", "3+"):
        at_depth = [row for row in records if row["loop_band"] == band]
        for loop_type in loop_types:
            selected = [row for row in at_depth if row["loop_type"] == loop_type]
            output.append(
                {
                    "pv_pr_loops": band,
                    "loop_type": loop_type,
                    "n": len(selected),
                    "share_within_depth": round(len(selected) / len(at_depth), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_feedback_chain_depth_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    """Measure whether each edit is bounded by observable validation feedback."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        if row["agent"] in {"moatless", "openhands"}:
            grouped[(row["agent"], row["instance_id"])].append(row)

    decisive = {"fail-to-pass", "fail-to-fail", "pass-to-fail", "pass-to-pass"}
    records: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        closed = sum(row["transition"] in decisive for row in rows)
        chain_type = "none" if closed == 0 else "complete" if closed == len(rows) else "partial"
        records.append(
            {
                "loop_band": "1" if len(rows) == 1 else "2" if len(rows) == 2 else "3+",
                "feedback_chain": chain_type,
                "resolved": int(rows[0]["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    for band in ("1", "2", "3+"):
        at_depth = [row for row in records if row["loop_band"] == band]
        for chain_type in ("complete", "partial", "none"):
            selected = [row for row in at_depth if row["feedback_chain"] == chain_type]
            output.append(
                {
                    "pv_pr_loops": band,
                    "feedback_chain": chain_type,
                    "n": len(selected),
                    "share_within_depth": round(len(selected) / len(at_depth), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_decision_type_rows(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    """Classify why the agent edited and whether it rechecked comparable behavior."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        if row["agent"] in {"moatless", "openhands"}:
            grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        depth = "1" if len(rows) == 1 else "2" if len(rows) == 2 else "3+"
        for row in rows:
            before, _, after = row["transition"].partition("-to-")
            comparable = row["scope_relation"] in {"same_scope", "expanded_scope"}
            if before == "fail" and after in {"pass", "fail"} and comparable:
                decision_type = "failure_driven_recheck"
            elif before == "fail":
                decision_type = "failure_driven_test_switch"
            elif before == "pass":
                decision_type = "edit_after_pass"
            else:
                decision_type = "edit_without_clear_failure"
            records.append(
                {
                    "loop_depth": depth,
                    "decision_type": decision_type,
                    "resolved": int(row["resolved"]),
                }
            )

    output: list[dict[str, object]] = []
    decision_types = (
        "failure_driven_recheck",
        "failure_driven_test_switch",
        "edit_after_pass",
        "edit_without_clear_failure",
    )
    for depth in ("1", "2", "3+"):
        at_depth = [row for row in records if row["loop_depth"] == depth]
        for decision_type in decision_types:
            selected = [row for row in at_depth if row["decision_type"] == decision_type]
            output.append(
                {
                    "pv_pr_loops": depth,
                    "decision_type": decision_type,
                    "loop_events": len(selected),
                    "share_within_depth": round(len(selected) / len(at_depth), 4),
                    "associated_resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_feedback_transition_rows(
    cases: list[dict[str, str]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        grouped[(row["agent"], row["instance_id"])].append(row)
    records: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        for index, row in enumerate(rows, start=1):
            transition = row["transition"]
            anchored = row["scope_relation"] in {"same_scope", "expanded_scope"}
            decisive = transition in {
                "fail-to-pass",
                "fail-to-fail",
                "pass-to-fail",
                "pass-to-pass",
            }
            if decisive and not anchored:
                mechanism = "shifted_validation"
            elif transition == "fail-to-pass":
                mechanism = "confirmed_recovery"
            elif transition == "fail-to-fail":
                mechanism = "persistent_failure"
            elif transition == "pass-to-fail":
                mechanism = "new_constraint_exposed"
            elif transition == "pass-to-pass":
                mechanism = "stable_pass"
            else:
                mechanism = "unclosed_feedback"
            records.append(
                {
                    "agent": row["agent"],
                    "first_pc_outcome": row["first_pc_outcome"],
                    "loop_position": "first" if index == 1 else "repeated",
                    "mechanism": mechanism,
                    "resolved": int(row["resolved"]),
                }
            )
    output: list[dict[str, object]] = []
    mechanisms = (
        "confirmed_recovery",
        "persistent_failure",
        "new_constraint_exposed",
        "stable_pass",
        "shifted_validation",
        "unclosed_feedback",
    )
    for position in ("first", "repeated"):
        rows = [row for row in records if row["loop_position"] == position]
        for mechanism in mechanisms:
            selected = [row for row in rows if row["mechanism"] == mechanism]
            output.append(
                {
                    "loop_position": position,
                    "feedback_mechanism": mechanism,
                    "n": len(selected),
                    "share": round(len(selected) / len(rows), 4),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    agent_output: list[dict[str, object]] = []
    for agent in ("lingxi", "moatless", "openhands"):
        for position in ("first", "repeated"):
            rows = [
                row
                for row in records
                if row["agent"] == agent and row["loop_position"] == position
            ]
            for mechanism in mechanisms:
                selected = [row for row in rows if row["mechanism"] == mechanism]
                agent_output.append(
                    {
                        "agent": agent,
                        "loop_position": position,
                        "feedback_mechanism": mechanism,
                        "n": len(selected),
                        "share": round(len(selected) / len(rows), 4),
                        "resolved_rate": round(
                            sum(int(row["resolved"]) for row in selected) / len(selected), 4
                        )
                        if selected
                        else "",
                    }
                )
    pc_output: list[dict[str, object]] = []
    for pc_outcome in ("+", "-"):
        for position in ("first", "repeated"):
            rows = [
                row
                for row in records
                if row["agent"] in {"moatless", "openhands"}
                and row["first_pc_outcome"] == pc_outcome
                and row["loop_position"] == position
            ]
            for mechanism in mechanisms:
                selected = [row for row in rows if row["mechanism"] == mechanism]
                pc_output.append(
                    {
                        "first_pc_outcome": pc_outcome,
                        "loop_position": position,
                        "feedback_mechanism": mechanism,
                        "n": len(selected),
                        "share": round(len(selected) / len(rows), 4) if rows else "",
                        "resolved_rate": round(
                            sum(int(row["resolved"]) for row in selected) / len(selected), 4
                        )
                        if selected
                        else "",
                    }
                )
    return output, agent_output, pc_output


def post_feedback_closure_rows(
    cases: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in cases:
        if row["agent"] in {"moatless", "openhands"}:
            grouped[(row["agent"], row["instance_id"])].append(row)
    records: list[dict[str, object]] = []
    decisive = {"fail-to-pass", "fail-to-fail", "pass-to-fail", "pass-to-pass"}
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["subtask_index"]))
        for index, row in enumerate(rows, start=1):
            records.append(
                {
                    "agent": row["agent"],
                    "first_pc_outcome": row["first_pc_outcome"],
                    "loop_position": "first" if index == 1 else "repeated",
                    "feedback_closure": "closed"
                    if row["transition"] in decisive
                    else "unclosed",
                    "resolved": int(row["resolved"]),
                }
            )

    def aggregate(group_field: str, groups: tuple[str, ...]) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for group in groups:
            for position in ("first", "repeated"):
                rows = [
                    row
                    for row in records
                    if row[group_field] == group and row["loop_position"] == position
                ]
                for closure in ("closed", "unclosed"):
                    selected = [row for row in rows if row["feedback_closure"] == closure]
                    output.append(
                        {
                            group_field: group,
                            "loop_position": position,
                            "feedback_closure": closure,
                            "n": len(selected),
                            "share": round(len(selected) / len(rows), 4),
                            "resolved_rate": round(
                                sum(int(row["resolved"]) for row in selected) / len(selected), 4
                            )
                            if selected
                            else "",
                        }
                    )
        return output

    return (
        aggregate("first_pc_outcome", ("+", "-")),
        aggregate("agent", ("moatless", "openhands")),
    )


def post_edit_expansion_rows(
    post_pairs: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in post_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)

    trajectories: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["loop_index"]))
        if len(rows) < 2:
            continue
        first_paths = {path for path in rows[0]["edit_paths"].split(";") if path}
        later_paths = {
            path for row in rows[1:] for path in row["edit_paths"].split(";") if path
        }
        trajectories.append(
            {
                "agent": rows[0]["agent"],
                "instance_id": rows[0]["instance_id"],
                "task_class": rows[0]["task_class"],
                "scope_class": (
                    "single_file"
                    if rows[0]["task_class"] in {"atomic_local", "multisite_single_file"}
                    else "multi_file"
                ),
                "loop_band": "2" if len(rows) == 2 else "3+",
                "edit_scope": "expanded" if later_paths - first_paths else "same",
                "resolved": int(rows[0]["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    for task_class in CLASS_ORDER:
        for band in ("2", "3+"):
            for edit_scope in ("same", "expanded"):
                rows = [
                    row
                    for row in trajectories
                    if row["task_class"] == task_class
                    and row["loop_band"] == band
                    and row["edit_scope"] == edit_scope
                ]
                if not rows:
                    continue
                output.append(
                    {
                        "task_class": task_class,
                        "task_type": CLASS_NAMES[task_class],
                        "pv_pr_loops": band,
                        "later_pr_edit_scope": edit_scope,
                        "n": len(rows),
                        "resolved_rate": round(
                            sum(int(row["resolved"]) for row in rows) / len(rows), 4
                        ),
                    }
                )
    for scope_class, scope_name in (("single_file", "单文件"), ("multi_file", "多文件")):
        for edit_scope in ("same", "expanded"):
            rows = [
                row
                for row in trajectories
                if row["scope_class"] == scope_class
                and row["loop_band"] == "3+"
                and row["edit_scope"] == edit_scope
            ]
            output.append(
                {
                    "task_class": scope_class,
                    "task_type": scope_name,
                    "pv_pr_loops": "3+",
                    "later_pr_edit_scope": edit_scope,
                    "n": len(rows),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in rows) / len(rows), 4
                    ),
                }
            )
    matched_output: list[dict[str, object]] = []
    for scope_class, scope_name in (("single_file", "单文件"), ("multi_file", "多文件")):
        by_instance: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in trajectories:
            if row["scope_class"] == scope_class and row["loop_band"] == "3+":
                by_instance[str(row["instance_id"])].append(row)
        differences: list[float] = []
        for rows in by_instance.values():
            same = [int(row["resolved"]) for row in rows if row["edit_scope"] == "same"]
            expanded = [int(row["resolved"]) for row in rows if row["edit_scope"] == "expanded"]
            if same and expanded:
                differences.append(sum(expanded) / len(expanded) - sum(same) / len(same))
        matched_output.append(
            {
                "scope_class": scope_class,
                "task_type": scope_name,
                "matched_instances": len(differences),
                "expanded_minus_same_delta_rr": round(
                    sum(differences) / len(differences), 4
                )
                if differences
                else "",
            }
        )
    return output, matched_output


def post_correct_file_expansion_rows(post_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in post_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["loop_index"]))
        if len(rows) < 3:
            continue
        first_paths = {path for path in rows[0]["edit_paths"].split(";") if path}
        later_paths = {
            path for row in rows[1:] for path in row["edit_paths"].split(";") if path
        }
        added_required = any(row["new_reference_paths"] for row in rows[1:])
        if added_required:
            expansion_type = "added_required_file"
        elif later_paths - first_paths:
            expansion_type = "added_other_file"
        else:
            expansion_type = "same_files"
        scope_class = (
            "single_file"
            if rows[0]["task_class"] in {"atomic_local", "multisite_single_file"}
            else "multi_file"
        )
        records.append(
            {
                "scope_class": scope_class,
                "expansion_type": expansion_type,
                "resolved": int(rows[0]["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    for scope_class, scope_name in (("single_file", "单文件"), ("multi_file", "多文件")):
        rows = [row for row in records if row["scope_class"] == scope_class]
        for expansion_type in ("same_files", "added_required_file", "added_other_file"):
            selected = [row for row in rows if row["expansion_type"] == expansion_type]
            output.append(
                {
                    "task_type": scope_name,
                    "expansion_type": expansion_type,
                    "n": len(selected),
                    "share": round(len(selected) / len(rows), 4) if rows else "",
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_loop_guidance_rows(
    trajectories: list[dict[str, str]], edit_expansion_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for scope_class, scope_name, task_classes in (
        ("single_file", "单文件", {"atomic_local", "multisite_single_file"}),
        (
            "multi_file",
            "多文件",
            {"intra_component_multifile", "cross_component_coordination"},
        ),
    ):
        for band, predicate in (
            ("0", lambda value: value == 0),
            ("1-2", lambda value: 1 <= value <= 2),
        ):
            rows = [
                row
                for row in trajectories
                if row["candidate_class"] in task_classes and predicate(int(row["post_loops"]))
            ]
            output.append(
                {
                    "scope_class": scope_class,
                    "task_type": scope_name,
                    "pv_pr_loops": band,
                    "later_pr_edit_scope": "not_applicable",
                    "n": len(rows),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in rows) / len(rows), 4
                    ),
                }
            )
        output.extend(
            {
                "scope_class": scope_class,
                "task_type": scope_name,
                "pv_pr_loops": "3+",
                "later_pr_edit_scope": str(row["later_pr_edit_scope"]),
                "n": int(row["n"]),
                "resolved_rate": float(row["resolved_rate"]),
            }
            for row in edit_expansion_rows
            if row["task_class"] == scope_class
        )
    return output


def total_loop_depth_rows(trajectories: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for loop_name, field in (("FR-FL", "pre_loops"), ("PV-PR", "post_loops")):
        for band, predicate in (
            ("0", lambda value: value == 0),
            ("1", lambda value: value == 1),
            ("2", lambda value: value == 2),
            ("3+", lambda value: value >= 3),
        ):
            rows = [row for row in trajectories if predicate(int(row[field]))]
            output.append(
                {
                    "loop": loop_name,
                    "loop_band": band,
                    "n": len(rows),
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in rows) / len(rows), 4
                    )
                    if rows
                    else "",
                }
            )
    return output


def pre_file_coverage_rows(summaries: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for task_class in CLASS_ORDER:
        for band in ("0-1", "2-3", "4-5", "6+"):
            rows = [
                row
                for row in summaries
                if row["task_class"] == task_class
                and (
                    (band == "0-1" and int(row["k"]) <= 1)
                    or (band == "2-3" and 2 <= int(row["k"]) <= 3)
                    or (band == "4-5" and 4 <= int(row["k"]) <= 5)
                    or (band == "6+" and int(row["k"]) >= 6)
                )
            ]
            for coverage in ("all", "some", "none"):
                selected = []
                for row in rows:
                    seen = int(row["reference_paths_seen"])
                    required = int(row["reference_path_count"])
                    current = "all" if required > 0 and seen >= required else "some" if seen else "none"
                    if current == coverage:
                        selected.append(row)
                output.append(
                    {
                        "task_class": task_class,
                        "task_type": CLASS_NAMES[task_class],
                        "fr_fl_loops": band,
                        "correct_file_coverage": coverage,
                        "n": len(selected),
                        "share_within_depth": round(len(selected) / len(rows), 4) if rows else "",
                        "resolved_rate": round(
                            sum(int(row["resolved"]) for row in selected) / len(selected), 4
                        )
                        if selected
                        else "",
                    }
                )
    return output


def pre_loop_attribute_depth_rows(
    trajectories: list[dict[str, str]], pre_pairs: list[dict[str, str]]
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pre_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    harmful_motifs = {
        "passive_revisit->passive_revisit",
        "probe_revisit->probe_revisit",
        "search_expand->probe_revisit",
    }
    for trajectory in trajectories:
        rows = sorted(
            grouped[(trajectory["agent"], trajectory["instance_id"])],
            key=lambda row: int(row["pair_index"]),
        )
        labels = []
        for row in rows:
            executed = row["fr_mode"] == "executed_failure_probe"
            expanded = bool(row["new_target_paths"])
            labels.append(
                "probe_expand"
                if executed and expanded
                else "probe_revisit"
                if executed
                else "search_expand"
                if expanded
                else "passive_revisit"
            )
        motifs = {f"{left}->{right}" for left, right in zip(labels, labels[1:])}
        records.append(
            {
                "agent": trajectory["agent"],
                "loop_band": (
                    "0"
                    if not rows
                    else "1"
                    if len(rows) == 1
                    else "2"
                    if len(rows) == 2
                    else "3+"
                ),
                "has_probe": int(any(label.startswith("probe_") for label in labels)),
                "has_expansion": int(any(label.endswith("expand") for label in labels)),
                "has_stagnation": int(bool(motifs & harmful_motifs)),
                "resolved": int(trajectory["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    for band in ("1", "2", "3+"):
        rows = [row for row in records if row["loop_band"] == band]
        stagnant = [row for row in rows if row["has_stagnation"]]
        progressing = [row for row in rows if not row["has_stagnation"]]
        weighted_deltas: list[tuple[float, float]] = []
        for agent in ("lingxi", "moatless", "openhands"):
            agent_stagnant = [row for row in stagnant if row["agent"] == agent]
            agent_progressing = [row for row in progressing if row["agent"] == agent]
            if not agent_stagnant or not agent_progressing:
                continue
            weight = len(agent_stagnant) * len(agent_progressing) / (
                len(agent_stagnant) + len(agent_progressing)
            )
            delta = sum(int(row["resolved"]) for row in agent_stagnant) / len(
                agent_stagnant
            ) - sum(int(row["resolved"]) for row in agent_progressing) / len(
                agent_progressing
            )
            weighted_deltas.append((weight, delta))
        output.append(
            {
                "fr_fl_loops": band,
                "n": len(rows),
                "has_executed_probe_share": round(
                    sum(int(row["has_probe"]) for row in rows) / len(rows), 4
                ),
                "has_target_expansion_share": round(
                    sum(int(row["has_expansion"]) for row in rows) / len(rows), 4
                ),
                "has_stagnation_share": round(len(stagnant) / len(rows), 4),
                "stagnation_rr": round(
                    sum(int(row["resolved"]) for row in stagnant) / len(stagnant), 4
                )
                if stagnant
                else "",
                "no_stagnation_rr": round(
                    sum(int(row["resolved"]) for row in progressing) / len(progressing), 4
                )
                if progressing
                else "",
                "agent_adjusted_delta_rr": round(
                    sum(weight * delta for weight, delta in weighted_deltas)
                    / sum(weight for weight, _ in weighted_deltas),
                    4,
                )
                if weighted_deltas
                else "",
            }
        )
    return output


def pre_mechanism_rows(pre_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pre_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["pair_index"]))
        depth = (
            "1"
            if len(rows) == 1
            else "2"
            if len(rows) == 2
            else "3-4"
            if len(rows) <= 4
            else "5+"
        )
        for row in rows:
            executed = row["fr_mode"] == "executed_failure_probe"
            searched = row.get("fl_has_search") == "1"
            mechanism = (
                "runtime_guided_search"
                if executed and searched
                else "runtime_guided_inspection"
                if executed
                else "static_search"
                if searched
                else "static_inspection"
            )
            records.append(
                {
                    "agent": row["agent"],
                    "task_class": row["task_class"],
                    "loop_depth": depth,
                    "mechanism": mechanism,
                    "resolved": int(row["resolved"]),
                }
            )
    output: list[dict[str, object]] = []
    mechanisms = (
        "static_search",
        "static_inspection",
        "runtime_guided_search",
        "runtime_guided_inspection",
    )
    for agent in ("total", "lingxi", "moatless", "openhands"):
        agent_records = [row for row in records if agent == "total" or row["agent"] == agent]
        for depth in ("1", "2", "3-4", "5+"):
            at_depth = [row for row in agent_records if row["loop_depth"] == depth]
            for mechanism in mechanisms:
                selected = [row for row in at_depth if row["mechanism"] == mechanism]
                output.append(
                    {
                        "agent": agent,
                        "fr_fl_loops": depth,
                        "mechanism": mechanism,
                        "loop_events": len(selected),
                        "share_within_depth": round(len(selected) / len(at_depth), 4)
                        if at_depth
                        else "",
                        "associated_resolved_rate": round(
                            sum(int(row["resolved"]) for row in selected) / len(selected), 4
                        )
                        if selected
                        else "",
                    }
                )
    return output


def pre_mechanism_task_rows(pre_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    mechanisms = (
        "static_search",
        "static_inspection",
        "runtime_guided_search",
        "runtime_guided_inspection",
    )
    records: list[dict[str, object]] = []
    for row in pre_pairs:
        executed = row["fr_mode"] == "executed_failure_probe"
        searched = row.get("fl_has_search") == "1"
        mechanism = (
            "runtime_guided_search"
            if executed and searched
            else "runtime_guided_inspection"
            if executed
            else "static_search"
            if searched
            else "static_inspection"
        )
        records.append(
            {
                "task_class": row["task_class"],
                "mechanism": mechanism,
                "resolved": int(row["resolved"]),
            }
        )

    output: list[dict[str, object]] = []
    for task_class in CLASS_ORDER:
        task_rows = [row for row in records if row["task_class"] == task_class]
        for mechanism in mechanisms:
            selected = [row for row in task_rows if row["mechanism"] == mechanism]
            output.append(
                {
                    "task_class": task_class,
                    "task_class_name": CLASS_NAMES[task_class],
                    "mechanism": mechanism,
                    "loop_events": len(selected),
                    "share_within_task": round(len(selected) / len(task_rows), 4),
                    "associated_resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def post_mechanism_rows(
    trajectories: list[dict[str, str]], post_pairs: list[dict[str, str]]
) -> list[dict[str, object]]:
    trajectory_by_key = {
        (row["agent"], row["instance_id"]): row for row in trajectories
    }
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in post_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)
    records: list[dict[str, object]] = []
    for key, rows in grouped.items():
        rows.sort(key=lambda row: int(row["loop_index"]))
        trajectory = trajectory_by_key[key]
        depth = (
            "1"
            if len(rows) == 1
            else "2"
            if len(rows) == 2
            else "3-4"
            if len(rows) <= 4
            else "5+"
        )
        for row in rows:
            mechanism = row["revision_mechanism"]
            records.append(
                {
                    "agent": row["agent"],
                    "loop_depth": depth,
                    "mechanism": mechanism,
                    "first_pc_outcome": trajectory["first_pc_outcome"],
                    "resolved": int(row["resolved"]),
                }
            )
    output: list[dict[str, object]] = []
    mechanisms = (
        "same_hunk_rework",
        "same_file_new_hunk",
        "new_file_responsibility_shift",
        "rollback_or_replacement",
    )
    for agent in ("total", "lingxi", "moatless", "openhands"):
        agent_records = [row for row in records if agent == "total" or row["agent"] == agent]
        for first_pc in ("total", "+", "-"):
            pc_records = [
                row
                for row in agent_records
                if first_pc == "total" or row["first_pc_outcome"] == first_pc
            ]
            for depth in ("1", "2", "3-4", "5+"):
                at_depth = [row for row in pc_records if row["loop_depth"] == depth]
                for mechanism in mechanisms:
                    selected = [row for row in at_depth if row["mechanism"] == mechanism]
                    output.append(
                        {
                            "agent": agent,
                            "first_pc_outcome": first_pc,
                            "pv_pr_loops": depth,
                            "mechanism": mechanism,
                            "loop_events": len(selected),
                            "share_within_depth": round(len(selected) / len(at_depth), 4)
                            if at_depth
                            else "",
                            "associated_resolved_rate": round(
                                sum(int(row["resolved"]) for row in selected) / len(selected), 4
                            )
                            if selected
                            else "",
                        }
                    )
    return output


def main() -> None:
    trajectories = read_csv(TRAJECTORIES)
    complete_keys = {(row["agent"], row["instance_id"]) for row in trajectories}
    task_class_by_key = {
        (row["agent"], row["instance_id"]): row["candidate_class"] for row in trajectories
    }
    first_pc_by_key = {
        (row["agent"], row["instance_id"]): row["first_pc_outcome"] for row in trajectories
    }
    pre_pairs = [
        row for row in read_csv(PRE_PAIRS) if (row["agent"], row["instance_id"]) in complete_keys
    ]
    post_cases = [
        row for row in read_csv(POST_CASES) if (row["agent"], row["instance_id"]) in complete_keys
    ]
    post_pairs = [
        row for row in read_csv(POST_PAIRS) if (row["agent"], row["instance_id"]) in complete_keys
    ]
    for row in post_cases:
        row["task_class"] = task_class_by_key[(row["agent"], row["instance_id"])]
        row["first_pc_outcome"] = first_pc_by_key[(row["agent"], row["instance_id"])]
    opportunities = pre_stagnation_opportunities(pre_pairs)
    pre_rows = aggregate_pre_stagnation(opportunities, "task_class", ["total", *CLASS_ORDER])
    pre_agent_rows = aggregate_pre_stagnation(
        opportunities, "agent", ["total", "lingxi", "moatless", "openhands"]
    )
    pre_scope_rows = aggregate_pre_stagnation(
        opportunities, "scope_class", ["total", "single_file", "multi_file"]
    )
    pre_evidence_rows = pre_evidence_target_rows(pre_pairs)
    executed_loop_rows = executed_feedback_loop_rows(trajectories, pre_pairs)
    executed_loop_matched_rows = executed_feedback_matched_rows(trajectories, pre_pairs)
    comparability_rows = validation_comparability_rows(post_cases)
    validation_task_rows = validation_by_task_rows(post_cases)
    post_scope_rows = post_scope_trajectory_rows(post_cases)
    post_rows = post_stagnation_rows(post_cases)
    post_trigger_summary = post_trigger_rows(post_pairs)
    post_trigger_evidence = post_trigger_evidence_rows(post_pairs)
    post_evidence_chain, post_evidence_cases = post_evidence_chain_rows(post_cases)
    post_loop_types = post_loop_type_depth_rows(post_cases)
    post_feedback_chain_depth = post_feedback_chain_depth_rows(post_cases)
    post_decision_types = post_decision_type_rows(post_cases)
    post_feedback_rows, post_feedback_agent_rows, post_feedback_pc_rows = (
        post_feedback_transition_rows(post_cases)
    )
    post_closure_pc_rows, post_closure_agent_rows = post_feedback_closure_rows(post_cases)
    post_edit_rows, post_edit_matched_rows = post_edit_expansion_rows(post_pairs)
    post_correct_file_expansion = post_correct_file_expansion_rows(post_pairs)
    post_guidance_rows = post_loop_guidance_rows(trajectories, post_edit_rows)
    total_depth_rows = total_loop_depth_rows(trajectories)
    pre_file_coverage = pre_file_coverage_rows(read_csv(PRE_SUMMARY))
    pre_depth_attributes = pre_loop_attribute_depth_rows(trajectories, pre_pairs)
    pre_mechanisms = pre_mechanism_rows(pre_pairs)
    pre_task_mechanisms = pre_mechanism_task_rows(pre_pairs)
    post_mechanisms = post_mechanism_rows(trajectories, post_pairs)
    write_csv(OUT / "pre_stagnation.csv", pre_rows)
    write_csv(OUT / "pre_stagnation_by_agent.csv", pre_agent_rows)
    write_csv(OUT / "pre_stagnation_by_scope.csv", pre_scope_rows)
    write_csv(OUT / "pre_evidence_target.csv", pre_evidence_rows)
    write_csv(OUT / "executed_feedback_loops.csv", executed_loop_rows)
    write_csv(OUT / "executed_feedback_loops_matched.csv", executed_loop_matched_rows)
    write_csv(OUT / "validation_comparability.csv", comparability_rows)
    write_csv(OUT / "validation_by_task.csv", validation_task_rows)
    write_csv(OUT / "post_scope_trajectories.csv", post_scope_rows)
    write_csv(OUT / "post_stagnation.csv", post_rows)
    write_csv(OUT / "post_trigger_summary.csv", post_trigger_summary)
    write_csv(OUT / "post_trigger_evidence.csv", post_trigger_evidence)
    write_csv(OUT / "post_evidence_chain.csv", post_evidence_chain)
    write_csv(OUT / "post_evidence_chain_cases.csv", post_evidence_cases)
    write_csv(OUT / "post_loop_types_by_depth.csv", post_loop_types)
    write_csv(OUT / "post_feedback_chain_by_depth.csv", post_feedback_chain_depth)
    write_csv(OUT / "post_decision_types_by_depth.csv", post_decision_types)
    write_csv(OUT / "post_feedback_transitions.csv", post_feedback_rows)
    write_csv(OUT / "post_feedback_transitions_by_agent.csv", post_feedback_agent_rows)
    write_csv(OUT / "post_feedback_transitions_by_first_pc.csv", post_feedback_pc_rows)
    write_csv(OUT / "post_feedback_closure_by_first_pc.csv", post_closure_pc_rows)
    write_csv(OUT / "post_feedback_closure_by_agent.csv", post_closure_agent_rows)
    write_csv(OUT / "post_edit_expansion.csv", post_edit_rows)
    write_csv(OUT / "post_edit_expansion_matched.csv", post_edit_matched_rows)
    write_csv(OUT / "post_correct_file_expansion.csv", post_correct_file_expansion)
    write_csv(OUT / "post_loop_guidance.csv", post_guidance_rows)
    write_csv(OUT / "loop_depth_total.csv", total_depth_rows)
    write_csv(OUT / "pre_correct_file_coverage.csv", pre_file_coverage)
    write_csv(OUT / "pre_loop_attributes_by_depth.csv", pre_depth_attributes)
    write_csv(OUT / "pre_loop_mechanisms_by_depth.csv", pre_mechanisms)
    write_csv(OUT / "pre_loop_mechanisms_by_task.csv", pre_task_mechanisms)
    write_csv(OUT / "post_loop_mechanisms_by_depth.csv", post_mechanisms)
    print(f"pre_pairs={len(pre_pairs)}")
    print(f"post_cases={len(post_cases)}")
    print(f"wrote={OUT}")


if __name__ == "__main__":
    main()
