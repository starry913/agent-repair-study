#!/usr/bin/env python3
"""Build trajectory-level evidence for the mechanisms behind APR repair loops."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "RQ1/data/rq1_2"
PRE_PAIRS = BASE / "mechanisms/preloop_pairs.csv"
TRAJECTORIES = BASE / "task_fit/trajectories_enriched.csv"
SUBTASKS = ROOT / "pre/pre-12/dataset/pre12_subtasks.csv"
VALIDATION = ROOT / "RQ1/audit/pr_validation_scope_cases.csv"
OUT = BASE / "deep_loops"

PRE_LABELS = {
    (True, True): "probe_expand",
    (True, False): "probe_revisit",
    (False, True): "search_expand",
    (False, False): "passive_revisit",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def rr(rows: list[dict[str, object]]) -> float | str:
    return round(sum(int(row["resolved"]) for row in rows) / len(rows), 4) if rows else ""


def label_pre(row: dict[str, str]) -> str:
    return PRE_LABELS[
        (
            row["fr_mode"] == "executed_failure_probe",
            bool(row["new_target_paths"]),
        )
    ]


def pre_chain_analysis(
    trajectories: list[dict[str, str]], pre_pairs: list[dict[str, str]]
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pre_pairs:
        grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    for row in trajectories:
        pairs = sorted(
            grouped[(row["agent"], row["instance_id"])],
            key=lambda item: int(item["pair_index"]),
        )
        sequence = [label_pre(item) for item in pairs]
        motifs = {f"{left}->{right}" for left, right in zip(sequence, sequence[1:])}
        records.append(
            {
                "agent": row["agent"],
                "instance_id": row["instance_id"],
                "resolved": int(row["resolved"]),
                "sequence": ";".join(sequence),
                "mechanisms": set(sequence),
                "motifs": motifs,
                "terminal": sequence[-1] if sequence else "none",
                "terminal_motif": (
                    f"{sequence[-2]}->{sequence[-1]}" if len(sequence) >= 2 else "none"
                ),
            }
        )

    features = sorted(
        {f"mechanism:{value}" for row in records for value in row["mechanisms"]}
        | {f"motif:{value}" for row in records for value in row["motifs"]}
        | {f"terminal:{row['terminal']}" for row in records}
        | {f"terminal_motif:{row['terminal_motif']}" for row in records}
    )
    summary: list[dict[str, object]] = []
    matched: list[dict[str, object]] = []
    by_agent: list[dict[str, object]] = []
    by_instance: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in records:
        by_instance[str(row["instance_id"])].append(row)

    for feature in features:
        kind, value = feature.split(":", 1)
        field = {
            "mechanism": "mechanisms",
            "motif": "motifs",
            "terminal": "terminal",
            "terminal_motif": "terminal_motif",
        }[kind]
        present = [
            row
            for row in records
            if (value in row[field] if kind in {"mechanism", "motif"} else value == row[field])
        ]
        absent = [row for row in records if row not in present]
        summary.append(
            {
                "feature_type": kind,
                "feature": value,
                "present_n": len(present),
                "present_rr": rr(present),
                "absent_n": len(absent),
                "absent_rr": rr(absent),
                "raw_delta": round(float(rr(present)) - float(rr(absent)), 4)
                if present and absent
                else "",
            }
        )
        differences = []
        for rows in by_instance.values():
            yes = [
                row
                for row in rows
                if (value in row[field] if kind in {"mechanism", "motif"} else value == row[field])
            ]
            no = [row for row in rows if row not in yes]
            if yes and no:
                differences.append(float(rr(yes)) - float(rr(no)))
        matched.append(
            {
                "feature_type": kind,
                "feature": value,
                "matched_instances": len(differences),
                "matched_delta_rr": round(sum(differences) / len(differences), 4)
                if differences
                else "",
                "positive": sum(value > 0 for value in differences),
                "negative": sum(value < 0 for value in differences),
                "ties": sum(value == 0 for value in differences),
            }
        )
        for agent in ("lingxi", "moatless", "openhands"):
            agent_rows = [row for row in records if row["agent"] == agent]
            agent_present = [row for row in agent_rows if row in present]
            agent_absent = [row for row in agent_rows if row not in present]
            by_agent.append(
                {
                    "feature_type": kind,
                    "feature": value,
                    "agent": agent,
                    "present_n": len(agent_present),
                    "present_rr": rr(agent_present),
                    "absent_n": len(agent_absent),
                    "absent_rr": rr(agent_absent),
                    "delta_rr": round(float(rr(agent_present)) - float(rr(agent_absent)), 4)
                    if agent_present and agent_absent
                    else "",
                }
            )
    return summary, matched, by_agent


def pre_execution_outcome_rows(pre_pairs: list[dict[str, str]]) -> list[dict[str, object]]:
    output = []
    executed = [row for row in pre_pairs if row["fr_mode"] == "executed_failure_probe"]
    for target in ("new_target", "revisited_target"):
        target_rows = [
            row
            for row in executed
            if bool(row["new_target_paths"]) == (target == "new_target")
        ]
        for outcome in ("fail", "pass", "unknown"):
            selected = []
            for row in target_rows:
                outcomes = set(filter(None, row["fr_run_outcomes"].split(";")))
                category = "fail" if "fail" in outcomes else "pass" if "pass" in outcomes else "unknown"
                if category == outcome:
                    selected.append(row)
            output.append(
                {
                    "localization_target": target,
                    "probe_outcome": outcome,
                    "n": len(selected),
                    "share_within_target": round(len(selected) / len(target_rows), 4)
                    if target_rows
                    else "",
                    "resolved_rate": round(
                        sum(int(row["resolved"]) for row in selected) / len(selected), 4
                    )
                    if selected
                    else "",
                }
            )
    return output


def pre_agent_adjusted_rows(by_agent: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in by_agent:
        grouped[(str(row["feature_type"]), str(row["feature"]))].append(row)
    output = []
    for (kind, feature), rows in sorted(grouped.items()):
        usable = [row for row in rows if row["delta_rr"] != ""]
        weights = [
            int(row["present_n"]) * int(row["absent_n"])
            / (int(row["present_n"]) + int(row["absent_n"]))
            for row in usable
        ]
        output.append(
            {
                "feature_type": kind,
                "feature": feature,
                "agents_with_contrast": len(usable),
                "agent_adjusted_delta_rr": round(
                    sum(weight * float(row["delta_rr"]) for weight, row in zip(weights, usable))
                    / sum(weights),
                    4,
                )
                if weights
                else "",
                "agents_positive": sum(float(row["delta_rr"]) > 0 for row in usable),
                "agents_negative": sum(float(row["delta_rr"]) < 0 for row in usable),
            }
        )
    return output


def exact_post_records(
    trajectories: list[dict[str, str]],
    subtasks: list[dict[str, str]],
    validations: list[dict[str, str]],
) -> list[dict[str, object]]:
    trajectory_by_key = {
        (row["agent"], row["instance_id"]): row for row in trajectories
    }
    validation_by_key = {
        (row["agent"], row["instance_id"], int(row["subtask_index"])): row
        for row in validations
    }
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in subtasks:
        grouped[(row["agent"], row["instance_id"])].append(row)

    records: list[dict[str, object]] = []
    for key, segments in grouped.items():
        trajectory = trajectory_by_key.get(key)
        if not trajectory:
            continue
        segments.sort(key=lambda row: int(row["subtask_index"]))
        pc = next((row for row in segments if row["subtask_code"] == "PC"), None)
        if not pc:
            continue
        loops = []
        for index, segment in enumerate(segments):
            if (
                segment["subtask_code"] != "PR"
                or index == 0
                or segments[index - 1]["subtask_code"] != "PV"
            ):
                continue
            validation = validation_by_key.get((*key, int(segment["subtask_index"])))
            decisive = validation and validation["transition"] in {
                "fail-to-pass",
                "fail-to-fail",
                "pass-to-fail",
                "pass-to-pass",
            }
            loops.append(
                {
                    "pv_outcome": segments[index - 1]["local_outcome"],
                    "pr_outcome": segment["local_outcome"],
                    "pr_basis": segment["local_outcome_basis"],
                    "closed": bool(decisive),
                    "transition": validation["transition"] if validation else "missing",
                }
            )
        records.append(
            {
                "agent": key[0],
                "instance_id": key[1],
                "resolved": int(trajectory["resolved"]),
                "first_pc": pc["local_outcome"],
                "loops": loops,
            }
        )
    return records


def band(value: int) -> str:
    return str(value) if value < 3 else "3+"


def post_depth_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for pc in ("+", "-"):
        for loop_band in ("0", "1", "2", "3+"):
            rows = [
                row
                for row in records
                if row["first_pc"] == pc and band(len(row["loops"])) == loop_band
            ]
            loop_items = [item for row in rows for item in row["loops"]]
            observable_loop_items = [
                item for row in rows if row["agent"] != "lingxi" for item in row["loops"]
            ]
            output.append(
                {
                    "first_pc": pc,
                    "loop_band": loop_band,
                    "n": len(rows),
                    "resolved_rate": rr(rows),
                    "any_pr_plus_share": round(
                        sum(any(item["pr_outcome"] == "+" for item in row["loops"]) for row in rows)
                        / len(rows),
                        4,
                    )
                    if rows and loop_band != "0"
                    else "",
                    "any_pr_minus_share": round(
                        sum(any(item["pr_outcome"] == "-" for item in row["loops"]) for row in rows)
                        / len(rows),
                        4,
                    )
                    if rows and loop_band != "0"
                    else "",
                    "closed_link_share": round(
                        sum(item["closed"] for item in observable_loop_items)
                        / len(observable_loop_items),
                        4,
                    )
                    if observable_loop_items
                    else "",
                }
            )
    return output


def pc_plus_mechanisms(records: list[dict[str, object]]) -> list[dict[str, object]]:
    classified: list[dict[str, object]] = []
    for row in records:
        if row["first_pc"] != "+" or not row["loops"]:
            continue
        outcomes = [item["pr_outcome"] for item in row["loops"]]
        if "-" in outcomes:
            mechanism = "negative_refinement"
        elif "?" in outcomes:
            mechanism = "uncertain_revision"
        elif row["agent"] != "lingxi" and all(item["closed"] for item in row["loops"]):
            mechanism = "aligned_and_closed"
        else:
            mechanism = "aligned_but_unclosed"
        classified.append({**row, "mechanism": mechanism})

    output = []
    for loop_band in ("1", "2", "3+"):
        rows_at_depth = [row for row in classified if band(len(row["loops"])) == loop_band]
        for mechanism in (
            "aligned_and_closed",
            "aligned_but_unclosed",
            "negative_refinement",
            "uncertain_revision",
        ):
            selected = [row for row in rows_at_depth if row["mechanism"] == mechanism]
            output.append(
                {
                    "loop_band": loop_band,
                    "mechanism": mechanism,
                    "n": len(selected),
                    "share": round(len(selected) / len(rows_at_depth), 4)
                    if rows_at_depth
                    else "",
                    "resolved_rate": rr(selected),
                }
            )
    return output


def pc_minus_recovery(records: list[dict[str, object]]) -> list[dict[str, object]]:
    classified = []
    for row in records:
        if row["first_pc"] != "-" or not row["loops"]:
            continue
        first_plus = next(
            (index for index, item in enumerate(row["loops"], start=1) if item["pr_outcome"] == "+"),
            None,
        )
        if first_plus is None:
            mechanism = "never_corrected"
            extra = -1
        else:
            extra = len(row["loops"]) - first_plus
            mechanism = "corrected_then_stop" if extra == 0 else "corrected_then_continue"
        classified.append({**row, "mechanism": mechanism, "extra": extra})

    output = []
    for mechanism in ("corrected_then_stop", "corrected_then_continue", "never_corrected"):
        selected = [row for row in classified if row["mechanism"] == mechanism]
        output.append(
            {
                "mechanism": mechanism,
                "n": len(selected),
                "share": round(len(selected) / len(classified), 4) if classified else "",
                "resolved_rate": rr(selected),
                "closed_link_share": round(
                    sum(
                        item["closed"]
                        for row in selected
                        if row["agent"] != "lingxi"
                        for item in row["loops"]
                    )
                    / sum(
                        len(row["loops"])
                        for row in selected
                        if row["agent"] != "lingxi"
                    ),
                    4,
                )
                if any(row["agent"] != "lingxi" for row in selected)
                else "",
            }
        )
    for extra_band, predicate in (
        ("0", lambda value: value == 0),
        ("1", lambda value: value == 1),
        ("2+", lambda value: value >= 2),
    ):
        selected = [row for row in classified if row["extra"] >= 0 and predicate(row["extra"])]
        output.append(
            {
                "mechanism": f"extra_after_first_pr_plus:{extra_band}",
                "n": len(selected),
                "share": "",
                "resolved_rate": rr(selected),
                "closed_link_share": round(
                    sum(
                        item["closed"]
                        for row in selected
                        if row["agent"] != "lingxi"
                        for item in row["loops"]
                    )
                    / sum(
                        len(row["loops"])
                        for row in selected
                        if row["agent"] != "lingxi"
                    ),
                    4,
                )
                if any(row["agent"] != "lingxi" for row in selected)
                else "",
            }
        )
    return output


def post_position_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for pc in ("+", "-"):
        relevant = [row for row in records if row["first_pc"] == pc]
        for position in (1, 2, 3, 4, 5):
            rows_at_position = [row for row in relevant if len(row["loops"]) >= position]
            items = [row["loops"][position - 1] for row in rows_at_position]
            observable_items = [
                row["loops"][position - 1]
                for row in rows_at_position
                if row["agent"] != "lingxi"
            ]
            output.append(
                {
                    "first_pc": pc,
                    "loop_position": f"{position}" if position < 5 else "5+",
                    "n": len(items),
                    "pr_plus_share": round(
                        sum(item["pr_outcome"] == "+" for item in items) / len(items), 4
                    )
                    if items
                    else "",
                    "pr_minus_share": round(
                        sum(item["pr_outcome"] == "-" for item in items) / len(items), 4
                    )
                    if items
                    else "",
                    "closed_share": round(
                        sum(item["closed"] for item in observable_items) / len(observable_items), 4
                    )
                    if observable_items
                    else "",
                    "pv_plus_share": round(
                        sum(item["pv_outcome"] == "+" for item in items) / len(items), 4
                    )
                    if items
                    else "",
                    "pv_minus_share": round(
                        sum(item["pv_outcome"] == "-" for item in items) / len(items), 4
                    )
                    if items
                    else "",
                }
            )
    return output


def initial_patch_scope_rows(
    trajectories: list[dict[str, str]], records: list[dict[str, object]]
) -> list[dict[str, object]]:
    post_by_key = {(row["agent"], row["instance_id"]): row for row in records}
    output = []
    for pc in ("+", "-"):
        for loop_band in ("0", "1", "2", "3+"):
            rows = [
                row
                for row in trajectories
                if row["first_pc_outcome"] == pc
                and band(len(post_by_key[(row["agent"], row["instance_id"])]["loops"]))
                == loop_band
            ]
            coverages = [
                int(row["pc_reference_file_hits"]) / int(row["source_file_count"])
                for row in rows
                if int(row["source_file_count"]) > 0
            ]
            output.append(
                {
                    "first_pc": pc,
                    "loop_band": loop_band,
                    "n": len(rows),
                    "resolved_rate": rr(rows),
                    "full_reference_file_coverage_share": round(
                        sum(value == 1 for value in coverages) / len(coverages), 4
                    )
                    if coverages
                    else "",
                    "mean_reference_file_coverage": round(
                        sum(coverages) / len(coverages), 4
                    )
                    if coverages
                    else "",
                    "multi_reference_file_share": round(
                        sum(int(row["source_file_count"]) > 1 for row in rows) / len(rows), 4
                    )
                    if rows
                    else "",
                }
            )
    return output


def post_trigger_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for pc in ("+", "-"):
        for position in ("first", "repeated"):
            items = []
            for row in records:
                if row["first_pc"] != pc:
                    continue
                selected = row["loops"][:1] if position == "first" else row["loops"][1:]
                items.extend(
                    {**item, "resolved": row["resolved"], "agent": row["agent"]}
                    for item in selected
                )
            for pv_outcome in ("+", "-", "?"):
                selected = [item for item in items if item["pv_outcome"] == pv_outcome]
                output.append(
                    {
                        "first_pc": pc,
                        "loop_position": position,
                        "pv_outcome": pv_outcome,
                        "n": len(selected),
                        "share": round(len(selected) / len(items), 4) if items else "",
                        "resolved_rate": rr(selected),
                        "pr_minus_share": round(
                            sum(item["pr_outcome"] == "-" for item in selected)
                            / len(selected),
                            4,
                        )
                        if selected
                        else "",
                        "closed_share": round(
                            sum(item["closed"] for item in selected if item["agent"] != "lingxi")
                            / sum(item["agent"] != "lingxi" for item in selected),
                            4,
                        )
                        if any(item["agent"] != "lingxi" for item in selected)
                        else "",
                    }
                )
    return output


def pc_minus_after_correction(records: list[dict[str, object]]) -> list[dict[str, object]]:
    classified = []
    for row in records:
        if row["first_pc"] != "-":
            continue
        first_plus = next(
            (index for index, item in enumerate(row["loops"]) if item["pr_outcome"] == "+"),
            None,
        )
        if first_plus is None:
            mechanism = "never_corrected"
        else:
            later = row["loops"][first_plus + 1 :]
            if not later:
                mechanism = "stop_after_correction"
            elif any(item["pr_outcome"] == "-" for item in later):
                mechanism = "relapse_after_correction"
            else:
                mechanism = "maintain_after_correction"
        classified.append({**row, "mechanism": mechanism})

    output = []
    for mechanism in (
        "stop_after_correction",
        "maintain_after_correction",
        "relapse_after_correction",
        "never_corrected",
    ):
        selected = [row for row in classified if row["mechanism"] == mechanism]
        output.append(
            {
                "mechanism": mechanism,
                "n": len(selected),
                "share": round(len(selected) / len(classified), 4) if classified else "",
                "resolved_rate": rr(selected),
                "mean_loops": round(
                    sum(len(row["loops"]) for row in selected) / len(selected), 2
                )
                if selected
                else "",
            }
        )
    return output


def pc_minus_first_correction(records: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in records:
        if row["first_pc"] != "-" or not row["loops"]:
            continue
        first_plus = next(
            (index for index, item in enumerate(row["loops"], start=1) if item["pr_outcome"] == "+"),
            None,
        )
        label = "never" if first_plus is None else str(first_plus) if first_plus <= 2 else "3+"
        grouped[label].append(row)
    output = []
    total = sum(len(rows) for rows in grouped.values())
    for label in ("1", "2", "3+", "never"):
        rows = grouped[label]
        output.append(
            {
                "first_pr_plus_position": label,
                "n": len(rows),
                "share": round(len(rows) / total, 4) if total else "",
                "resolved_rate": rr(rows),
                "mean_total_loops": round(
                    sum(len(row["loops"]) for row in rows) / len(rows), 2
                )
                if rows
                else "",
            }
        )
    return output


def normalize_pr_basis(value: str) -> str:
    if value == "edit opposes reference direction":
        return "opposes_reference_direction"
    if value == "source edit outside reference files":
        return "outside_reference_files"
    if value == "validation pass-to-fail":
        return "validation_regression"
    if value == "edit follows reference direction":
        return "follows_reference_direction"
    if value == "reference target without opposing decisive evidence":
        return "reference_target_no_opposition"
    if value == "validation fail-to-pass":
        return "validation_improvement"
    return value or "unknown"


def pr_basis_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for pc in ("+", "-"):
        for position in ("first", "repeated"):
            items = []
            for row in records:
                if row["first_pc"] != pc:
                    continue
                selected = row["loops"][:1] if position == "first" else row["loops"][1:]
                items.extend(selected)
            for outcome in ("+", "-"):
                outcome_items = [item for item in items if item["pr_outcome"] == outcome]
                bases: dict[str, list[dict[str, object]]] = defaultdict(list)
                for item in outcome_items:
                    bases[normalize_pr_basis(str(item["pr_basis"]))].append(item)
                for basis, selected in sorted(bases.items(), key=lambda item: -len(item[1])):
                    output.append(
                        {
                            "first_pc": pc,
                            "loop_position": position,
                            "pr_outcome": outcome,
                            "basis": basis,
                            "n": len(selected),
                            "share_within_outcome": round(
                                len(selected) / len(outcome_items), 4
                            ),
                        }
                    )
    return output


def post_outcome_sequences(records: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for pc in ("+", "-"):
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in records:
            if row["first_pc"] != pc or not row["loops"]:
                continue
            sequence = "->".join(item["pr_outcome"] for item in row["loops"])
            grouped[sequence].append(row)
        for sequence, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            output.append(
                {
                    "first_pc": pc,
                    "pr_outcome_sequence": sequence,
                    "n": len(rows),
                    "resolved_rate": rr(rows),
                    "closed_link_share": round(
                        sum(item["closed"] for row in rows for item in row["loops"])
                        / sum(len(row["loops"]) for row in rows),
                        4,
                    ),
                }
            )
    return output


def main() -> None:
    trajectories = read_csv(TRAJECTORIES)
    pre_summary, pre_matched, pre_by_agent = pre_chain_analysis(
        trajectories, read_csv(PRE_PAIRS)
    )
    post_records = exact_post_records(
        trajectories, read_csv(SUBTASKS), read_csv(VALIDATION)
    )
    write_csv("pre_chain_features.csv", pre_summary)
    write_csv("pre_chain_matched.csv", pre_matched)
    write_csv("pre_chain_by_agent.csv", pre_by_agent)
    write_csv("pre_chain_agent_adjusted.csv", pre_agent_adjusted_rows(pre_by_agent))
    write_csv("pre_execution_outcomes.csv", pre_execution_outcome_rows(read_csv(PRE_PAIRS)))
    write_csv("post_depth.csv", post_depth_rows(post_records))
    write_csv("pc_plus_mechanisms.csv", pc_plus_mechanisms(post_records))
    write_csv("pc_minus_recovery.csv", pc_minus_recovery(post_records))
    write_csv("post_by_position.csv", post_position_rows(post_records))
    write_csv("post_outcome_sequences.csv", post_outcome_sequences(post_records))
    write_csv("initial_patch_scope.csv", initial_patch_scope_rows(trajectories, post_records))
    write_csv("post_triggers.csv", post_trigger_rows(post_records))
    write_csv("pc_minus_after_correction.csv", pc_minus_after_correction(post_records))
    write_csv("pc_minus_first_correction.csv", pc_minus_first_correction(post_records))
    write_csv("pr_basis.csv", pr_basis_rows(post_records))
    print(f"trajectories={len(trajectories)}")
    print(f"post_trajectories={len(post_records)}")
    print(f"post_loops={sum(len(row['loops']) for row in post_records)}")
    print(f"wrote={OUT}")


if __name__ == "__main__":
    main()
