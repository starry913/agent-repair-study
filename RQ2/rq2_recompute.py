#!/usr/bin/env python3
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBTASKS = ROOT / "pre/pre-12/dataset/pre12_subtasks.csv"
ACTIONS = ROOT / "pre/pre-12/dataset/pre12_actions.csv"
REFERENCES = ROOT / "pre/pre-12/metadata/pre12_reference_patch_meta.csv"
OUT = ROOT / "RQ2/data/pro"
AGENTS = ("lingxi", "moatless", "openhands")


def read_csv(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(name, rows, fields=None):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def paths(row):
    return {item for item in row.get("paths", "").split(";") if item}


def split_paths(value):
    return {item for item in value.split(";") if item}


def action_slice(action_groups, segment):
    key = (segment["agent"], segment["instance_id"])
    start = int(segment["start_event"])
    end = int(segment["end_event"])
    return [row for row in action_groups[key] if start <= int(row["event_index"]) <= end]


def product_edit_paths(action_groups, segment):
    return {
        row["path"]
        for row in action_slice(action_groups, segment)
        if row["is_product_source_edit"] == "1" and row["path"]
    }


def validation_feedback(events):
    outcomes = [
        row["outcome"]
        for row in events
        if row["action"] == "Run" and row["outcome"] in {"pass", "fail"}
    ]
    if not outcomes:
        return "unknown"
    if set(outcomes) == {"pass"}:
        return "pass_only"
    if set(outcomes) == {"fail"}:
        return "fail_only"
    return f"mixed_last_{outcomes[-1]}"


def source_paths(action_groups, segment):
    return {
        row["path"]
        for row in action_slice(action_groups, segment)
        if row["is_source_path"] == "1" and row["path"]
    }


def path_relation(candidates, references):
    if not candidates:
        return "no_source_candidate"
    candidate_dirs = {str(Path(path).parent) for path in candidates}
    reference_dirs = {str(Path(path).parent) for path in references}
    if candidate_dirs & reference_dirs:
        return "same_directory"

    def package(path):
        parts = Path(path).parts
        return parts[:2] if len(parts) >= 2 else parts[:1]

    if {package(path) for path in candidates} & {package(path) for path in references}:
        return "same_package"
    return "cross_package"


def conditional_rows(records, source_key, target_key, section):
    output = []
    for agent in ("total",) + AGENTS:
        selected = records if agent == "total" else [r for r in records if r["agent"] == agent]
        denominators = Counter(r[source_key] for r in selected)
        counts = Counter((r[source_key], r[target_key]) for r in selected)
        for (source, target), n in sorted(counts.items()):
            output.append(
                {
                    "section": section,
                    "agent": agent,
                    "source_outcome": source,
                    "target_outcome": target,
                    "n": n,
                    "conditional_share": round(n / denominators[source], 4),
                }
            )
    return output


def mechanism_rows(records, mechanism_key, section):
    output = []
    for agent in ("total",) + AGENTS:
        selected = records if agent == "total" else [r for r in records if r["agent"] == agent]
        counts = Counter(r[mechanism_key] for r in selected)
        total = sum(counts.values())
        for mechanism, n in sorted(counts.items()):
            output.append(
                {
                    "section": section,
                    "agent": agent,
                    "mechanism": mechanism,
                    "n": n,
                    "share": round(n / total, 4) if total else 0,
                }
            )
    return output


def main():
    subtasks = read_csv(SUBTASKS)
    actions = read_csv(ACTIONS)
    references = {
        row["instance_id"]: split_paths(row["patch_files"])
        for row in read_csv(REFERENCES)
    }

    sequences = defaultdict(list)
    for row in subtasks:
        row["subtask_index_i"] = int(row["subtask_index"])
        sequences[(row["agent"], row["instance_id"])].append(row)
    for sequence in sequences.values():
        sequence.sort(key=lambda row: row["subtask_index_i"])

    action_groups = defaultdict(list)
    for row in actions:
        action_groups[(row["agent"], row["instance_id"])].append(row)
    for group in action_groups.values():
        group.sort(key=lambda row: int(row["event_index"]))

    adjacent = []
    rq21_cases = []
    rq21_factor_records = []
    rq22_pairs = []
    rq22_cases = []
    rq23_cases = []
    rq23_all = []
    triads = []

    for (agent, instance_id), sequence in sequences.items():
        for index in range(len(sequence) - 1):
            left, right = sequence[index], sequence[index + 1]
            adjacent.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "from_type": left["subtask_code"],
                    "from_outcome": left["local_outcome"],
                    "to_type": right["subtask_code"],
                    "to_outcome": right["local_outcome"],
                }
            )

            if left["subtask_code"] == "FR" and left["local_outcome"] == "-" and right["subtask_code"] == "FL":
                earlier = sequence[:index]
                reference_paths = references.get(instance_id, set())
                prior_fl_plus = any(
                    row["subtask_code"] == "FL" and row["local_outcome"] == "+" for row in earlier
                )
                feedback = validation_feedback(action_slice(action_groups, left))
                rq21_factor_records.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "fl_positive": int(right["local_outcome"] == "+"),
                        "prior_fl_plus": "yes" if prior_fl_plus else "no",
                        "target_exposed_in_fr": (
                            "yes" if paths(left) & reference_paths else "no"
                        ),
                        "execution_feedback": feedback,
                    }
                )

            if (
                left["subtask_code"] == "FR"
                and left["local_outcome"] == "-"
                and right["subtask_code"] == "FL"
                and right["local_outcome"] == "+"
            ):
                earlier = sequence[:index]
                reference_paths = references.get(instance_id, set())
                prior_targets = set()
                for row in earlier:
                    if row["subtask_code"] == "FL" and row["local_outcome"] == "+":
                        prior_targets |= paths(row) & reference_paths
                current_targets = paths(right) & reference_paths
                if prior_targets and current_targets - prior_targets:
                    mechanism = "expand_known_reference_target"
                elif prior_targets:
                    mechanism = "reconfirm_known_reference_target"
                elif left["has_run"] == "True":
                    mechanism = "new_localization_after_execution"
                else:
                    mechanism = "new_localization_without_execution"
                rq21_cases.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "fr_index": left["subtask_index"],
                        "fl_index": right["subtask_index"],
                        "mechanism": mechanism,
                        "fr_actions": left["action_sequence"],
                        "fl_actions": right["action_sequence"],
                    }
                )

            if left["subtask_code"] == "PV" and right["subtask_code"] == "PR":
                feedback = validation_feedback(action_slice(action_groups, left))
                prior_patch_paths = set()
                for row in sequence[: index + 1]:
                    if row["subtask_code"] in {"PC", "PR"}:
                        prior_patch_paths |= product_edit_paths(action_groups, row)
                refinement_paths = product_edit_paths(action_groups, right)
                scope = "new_file" if refinement_paths - prior_patch_paths else "existing_file"
                mechanism = f"{feedback}__{scope}"
                case = {
                    "agent": agent,
                    "instance_id": instance_id,
                    "pv_index": left["subtask_index"],
                    "pr_index": right["subtask_index"],
                    "pv_outcome": left["local_outcome"],
                    "pr_outcome": right["local_outcome"],
                    "feedback": feedback,
                    "scope": scope,
                    "mechanism": mechanism,
                    "pr_basis": right["local_outcome_basis"],
                }
                rq23_all.append(case)
                if left["local_outcome"] == "+" and right["local_outcome"] == "+":
                    rq23_cases.append(case)

        first_pc_index = next(
            (i for i, row in enumerate(sequence) if row["subtask_code"] == "PC"), None
        )
        if first_pc_index is not None:
            prior = sequence[:first_pc_index]
            latest_fl_index = next(
                (i for i in range(len(prior) - 1, -1, -1) if prior[i]["subtask_code"] == "FL"),
                None,
            )
            if latest_fl_index is not None:
                fl = prior[latest_fl_index]
                pc = sequence[first_pc_index]
                earlier = prior[:latest_fl_index]
                earlier_fl_plus = any(
                    row["subtask_code"] == "FL" and row["local_outcome"] == "+"
                    for row in earlier
                )
                pair = {
                    "agent": agent,
                    "instance_id": instance_id,
                    "fl_outcome": fl["local_outcome"],
                    "pc_outcome": pc["local_outcome"],
                    "earlier_fl_plus": "yes" if earlier_fl_plus else "no",
                    "candidate_relation": path_relation(
                        source_paths(action_groups, fl), references.get(instance_id, set())
                    ),
                }
                rq22_pairs.append(pair)
                if fl["local_outcome"] == "-" and pc["local_outcome"] == "+":
                    reference_paths = references.get(instance_id, set())
                    earlier_targets = set()
                    for row in earlier:
                        if row["subtask_code"] == "FL" and row["local_outcome"] == "+":
                            earlier_targets |= paths(row) & reference_paths
                    pc_targets = product_edit_paths(action_groups, pc) & reference_paths
                    if earlier_targets and pc_targets - earlier_targets:
                        mechanism = "patch_expands_beyond_earlier_localization"
                    elif earlier_targets:
                        mechanism = "patch_returns_to_earlier_fault_target"
                    else:
                        exposed_elsewhere = any(paths(row) & pc_targets for row in prior)
                        mechanism = (
                            "target_exposed_outside_fault_localization"
                            if exposed_elsewhere
                            else "target_first_exposed_by_patch"
                        )
                    rq22_cases.append(
                        {
                            "agent": agent,
                            "instance_id": instance_id,
                            "fl_index": fl["subtask_index"],
                            "pc_index": pc["subtask_index"],
                            "mechanism": mechanism,
                            "fl_actions": fl["action_sequence"],
                            "pc_actions": pc["action_sequence"],
                        }
                    )

        for index in range(len(sequence) - 2):
            first, middle, last = sequence[index : index + 3]
            if [row["subtask_code"] for row in (first, middle, last)] == ["PV", "PR", "PV"]:
                triads.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "pv1_outcome": first["local_outcome"],
                        "pr_outcome": middle["local_outcome"],
                        "pv2_outcome": last["local_outcome"],
                    }
                )

    fr_fl = [r for r in adjacent if r["from_type"] == "FR" and r["to_type"] == "FL"]
    pv_pr = [r for r in adjacent if r["from_type"] == "PV" and r["to_type"] == "PR"]

    write_csv(
        "rq21_fr_fl_transitions.csv",
        conditional_rows(fr_fl, "from_outcome", "to_outcome", "FR_to_FL"),
    )
    write_csv("rq21_fr_minus_fl_plus_cases.csv", rq21_cases)
    write_csv(
        "rq21_fr_minus_fl_plus_mechanisms.csv",
        mechanism_rows(rq21_cases, "mechanism", "FR-_to_FL+"),
    )
    factor_rows = []
    for factor in ("prior_fl_plus", "target_exposed_in_fr", "execution_feedback"):
        for history in ("all", "no_prior_FL+"):
            selected = rq21_factor_records
            if history == "no_prior_FL+":
                selected = [r for r in selected if r["prior_fl_plus"] == "no"]
            counts = Counter(r[factor] for r in selected)
            positives = Counter(r[factor] for r in selected if r["fl_positive"])
            for value, n in sorted(counts.items()):
                factor_rows.append(
                    {
                        "history_scope": history,
                        "factor": factor,
                        "value": value,
                        "n": n,
                        "FL_plus_n": positives[value],
                        "FL_plus_rate": round(positives[value] / n, 4),
                    }
                )
    write_csv("rq21_fr_minus_recovery_factors.csv", factor_rows)

    write_csv(
        "rq22_latest_fl_first_pc.csv",
        conditional_rows(rq22_pairs, "fl_outcome", "pc_outcome", "latest_FL_to_first_PC"),
    )
    history_rows = []
    for agent in ("total",) + AGENTS:
        selected = rq22_pairs if agent == "total" else [r for r in rq22_pairs if r["agent"] == agent]
        selected = [r for r in selected if r["fl_outcome"] == "-"]
        denominators = Counter(r["earlier_fl_plus"] for r in selected)
        counts = Counter((r["earlier_fl_plus"], r["pc_outcome"]) for r in selected)
        for (history, outcome), n in sorted(counts.items()):
            history_rows.append(
                {
                    "agent": agent,
                    "earlier_FL_plus": history,
                    "PC_outcome": outcome,
                    "n": n,
                    "conditional_share": round(n / denominators[history], 4),
                }
            )
    write_csv("rq22_fl_minus_history_strata.csv", history_rows)
    relation_rows = []
    for history in ("all", "no_prior_FL+"):
        selected = [r for r in rq22_pairs if r["fl_outcome"] == "-"]
        if history == "no_prior_FL+":
            selected = [r for r in selected if r["earlier_fl_plus"] == "no"]
        counts = Counter(r["candidate_relation"] for r in selected)
        positives = Counter(
            r["candidate_relation"] for r in selected if r["pc_outcome"] == "+"
        )
        for relation, n in sorted(counts.items()):
            relation_rows.append(
                {
                    "history_scope": history,
                    "candidate_relation": relation,
                    "n": n,
                    "PC_plus_n": positives[relation],
                    "PC_plus_rate": round(positives[relation] / n, 4),
                }
            )
    write_csv("rq22_fl_minus_candidate_distance.csv", relation_rows)
    write_csv("rq22_fl_minus_pc_plus_cases.csv", rq22_cases)
    write_csv(
        "rq22_fl_minus_pc_plus_mechanisms.csv",
        mechanism_rows(rq22_cases, "mechanism", "FL-_to_PC+"),
    )

    write_csv(
        "rq23_pv_pr_transitions.csv",
        conditional_rows(pv_pr, "from_outcome", "to_outcome", "PV_to_PR"),
    )
    write_csv("rq23_pv_plus_pr_plus_cases.csv", rq23_cases)
    write_csv(
        "rq23_pv_plus_pr_plus_mechanisms.csv",
        mechanism_rows(rq23_cases, "mechanism", "PV+_to_PR+"),
    )
    feedback_pr = []
    for agent in ("total",) + AGENTS:
        selected = [r for r in rq23_all if r["pv_outcome"] == "+"]
        if agent != "total":
            selected = [r for r in selected if r["agent"] == agent]
        denominators = Counter(r["feedback"] for r in selected)
        counts = Counter((r["feedback"], r["pr_outcome"]) for r in selected)
        for (feedback, outcome), n in sorted(counts.items()):
            feedback_pr.append(
                {
                    "agent": agent,
                    "actual_feedback": feedback,
                    "pr_outcome": outcome,
                    "n": n,
                    "conditional_share": round(n / denominators[feedback], 4),
                }
            )
    write_csv("rq23_pv_plus_feedback_to_pr.csv", feedback_pr)
    write_csv(
        "rq23_pv_pr_pv_triads.csv",
        conditional_rows(
            [
                {**row, "source_state": f"PV{row['pv1_outcome']}->PR{row['pr_outcome']}"}
                for row in triads
            ],
            "source_state",
            "pv2_outcome",
            "PV_PR_PV",
        ),
    )

    audit = [
        {"metric": "trajectories", "value": len(sequences)},
        {"metric": "subtask_records", "value": len(subtasks)},
        {"metric": "FR_to_FL_adjacent", "value": len(fr_fl)},
        {"metric": "FR-_to_FL+", "value": len(rq21_cases)},
        {"metric": "latest_FL_to_first_PC", "value": len(rq22_pairs)},
        {"metric": "FL-_to_PC+", "value": len(rq22_cases)},
        {"metric": "PV_to_PR_adjacent", "value": len(pv_pr)},
        {"metric": "PV+_to_PR+", "value": len(rq23_cases)},
        {"metric": "PV_PR_PV", "value": len(triads)},
    ]
    write_csv("audit.csv", audit)
    for row in audit:
        print(f"{row['metric']}={row['value']}")


if __name__ == "__main__":
    main()
