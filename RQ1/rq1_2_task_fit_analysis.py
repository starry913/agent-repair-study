#!/usr/bin/env python3
"""Exploratory task-pathway fit analysis for RQ1.2.

Task classes are derived only from SWE-bench issue/reference artifacts.  Agent
pathways and resolved labels are joined afterwards so the taxonomy cannot be
defined by the outcome it is intended to explain.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np
from scipy.stats import chi2_contingency


ROOT = Path(__file__).resolve().parents[1]
PRE12_DIR = Path(os.environ.get("PRE12_DIR", ROOT / "pre/pre-12/dataset"))
OUT_DIR = Path(os.environ.get("RQ12_OUT_DIR", ROOT / "RQ1/data/rq1_2/task_fit"))


def json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def norm_path(path: str) -> str:
    return str(path or "").replace("\\", "/").removeprefix("a/").removeprefix("b/")


def is_test_path(path: str) -> bool:
    path = norm_path(path).lower()
    parts = [part for part in path.split("/") if part]
    base = parts[-1] if parts else ""
    stem = base.rsplit(".", 1)[0]
    return (
        any(part in {"test", "tests", "testing", "fixtures"} for part in parts[:-1])
        or stem.startswith("test_")
        or stem.endswith("_test")
    )


def is_doc_path(path: str) -> bool:
    path = norm_path(path).lower()
    parts = path.split("/")
    return (
        any(part in {"doc", "docs", "documentation", "news", "changelog"} for part in parts)
        or path.endswith((".md", ".rst", ".txt"))
    )


def is_config_path(path: str) -> bool:
    path = norm_path(path).lower()
    base = path.rsplit("/", 1)[-1]
    return base in {
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
        "tox.ini",
        "makefile",
        "manifest.in",
    } or path.endswith((".toml", ".yaml", ".yml", ".ini", ".cfg"))


def parse_diff(patch: str) -> dict[str, object]:
    files: set[str] = set()
    source_files: set[str] = set()
    test_files: set[str] = set()
    doc_files: set[str] = set()
    config_files: set[str] = set()
    parents: set[str] = set()
    top_components: set[str] = set()
    source_parents: set[str] = set()
    source_top_components: set[str] = set()
    added = 0
    removed = 0
    hunks = 0
    function_hunks = 0
    current = ""

    for line in (patch or "").splitlines():
        if line.startswith("diff --git "):
            match = re.search(r" b/(\S+)", line)
            current = norm_path(match.group(1)) if match else ""
            if current:
                files.add(current)
        elif line.startswith("+++ b/"):
            current = norm_path(line[6:].strip())
            files.add(current)
        elif line.startswith("@@"):
            hunks += 1
            context = line.split("@@", 2)[-1].strip()
            if re.search(r"\b(?:def|class|function|method)\b", context):
                function_hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    for path in files:
        if is_test_path(path):
            test_files.add(path)
        elif is_doc_path(path):
            doc_files.add(path)
        elif is_config_path(path):
            config_files.add(path)
        else:
            source_files.add(path)
        parts = [part for part in path.split("/") if part]
        if len(parts) > 1:
            parents.add("/".join(parts[:-1]))
            top_components.add(parts[0])
        elif parts:
            parents.add(".")
            top_components.add(".")

    for path in source_files:
        parts = [part for part in path.split("/") if part]
        if len(parts) > 1:
            source_parents.add("/".join(parts[:-1]))
            source_top_components.add(parts[0])
        elif parts:
            source_parents.add(".")
            source_top_components.add(".")

    return {
        "patch_file_count": len(files),
        "source_file_count": len(source_files),
        "patch_test_file_count": len(test_files),
        "doc_file_count": len(doc_files),
        "config_file_count": len(config_files),
        "parent_count": len(parents),
        "top_component_count": len(top_components),
        "source_parent_count": len(source_parents),
        "source_top_component_count": len(source_top_components),
        "hunk_count": hunks,
        "function_hunk_count": function_hunks,
        "added_loc": added,
        "removed_loc": removed,
        "changed_loc": added + removed,
        "patch_files": ";".join(sorted(files)),
        "source_files": ";".join(sorted(source_files)),
    }


def issue_features(statement: str) -> dict[str, object]:
    text = statement or ""
    low = text.lower()
    has_fence = bool(re.search(r"```[^\n]*\n.+?```", text, re.S))
    has_prompt = bool(re.search(r"(?m)^\s*(?:>>>|\$\s+|In \[\d+\]:)", text))
    has_traceback = "traceback (most recent call last)" in low or bool(
        re.search(r"(?m)^\s*(?:File \".+\", line \d+|\w*(?:Error|Exception):\s+.+)$", text)
    )
    has_test_command = bool(re.search(r"\b(?:pytest|tox|unittest|python\s+-m\s+\w*test)\b", low))
    has_test_id = bool(
        re.search(r"(?:^|[/\s])test_[\w.]+\.py(?:::\S+)?|\btest_[a-zA-Z0-9_]+\b", text)
    )
    has_repro_cue = bool(
        re.search(r"\b(?:steps? to reproduce|reproduc(?:e|es|ed|ible|tion)|minimal example|example to reproduce)\b", low)
    )
    has_expected = bool(re.search(r"\b(?:expected|should (?:be|return|raise|produce|show|not)|expect(?:ed)?)\b", low))
    has_actual = bool(re.search(r"\b(?:actual|instead|currently|observed|but (?:it|this)|got\b)\b", low))
    has_output = bool(re.search(r"\b(?:output|result|returns?|raises?|exception|error|warning|fails?)\b", low))
    has_numbered_steps = bool(re.search(r"(?m)^\s*(?:\d+[.)]|step\s+\d+)\s+", low))
    executable = bool(
        (has_fence or has_prompt or has_test_command or has_numbered_steps)
        and (has_traceback or has_repro_cue or has_expected or has_actual or has_output)
    )
    explicit_oracle = bool(has_traceback or has_test_id or (has_expected and has_actual))
    if executable:
        observability = "executable"
    elif explicit_oracle:
        observability = "explicit_symptom"
    else:
        observability = "specification_only"
    return {
        "statement_chars": len(text),
        "statement_lines": len(text.splitlines()),
        "has_code_fence": int(has_fence),
        "has_prompt_example": int(has_prompt),
        "has_traceback": int(has_traceback),
        "has_test_command": int(has_test_command),
        "has_test_identifier": int(has_test_id),
        "has_repro_cue": int(has_repro_cue),
        "has_expected": int(has_expected),
        "has_actual": int(has_actual),
        "has_output_cue": int(has_output),
        "has_numbered_steps": int(has_numbered_steps),
        "executable_evidence": int(executable),
        "explicit_oracle": int(explicit_oracle),
        "observability": observability,
    }


def test_file_from_id(test_id: str) -> str:
    value = str(test_id or "").split("::", 1)[0]
    return norm_path(value)


def load_tasks() -> list[dict[str, object]]:
    candidates = sorted(
        Path.home().glob(".cache/huggingface/hub/datasets--princeton-nlp--SWE-bench_Verified/blobs/*"),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    explicit = os.environ.get("SWE_BENCH_VERIFIED_PARQUET")
    parquet = Path(explicit).expanduser() if explicit else next((path for path in candidates if path.stat().st_size > 100_000), None)
    if parquet is None:
        raise FileNotFoundError("Set SWE_BENCH_VERIFIED_PARQUET to the reference Parquet file, or populate the SWE-bench Verified Hugging Face cache")
    con = duckdb.connect()
    result = con.execute("select * from read_parquet(?)", [str(parquet)])
    columns = [desc[0] for desc in result.description]
    tasks = []
    difficulty_order = {"<15 min fix": 0, "15 min - 1 hour": 1, "1-4 hours": 2, ">4 hours": 3}
    for values in result.fetchall():
        raw = dict(zip(columns, values))
        fail_to_pass = json_list(raw.get("FAIL_TO_PASS", "[]"))
        pass_to_pass = json_list(raw.get("PASS_TO_PASS", "[]"))
        fail_files = {test_file_from_id(item) for item in fail_to_pass if item}
        patch = parse_diff(raw.get("patch", ""))
        test_patch = parse_diff(raw.get("test_patch", ""))
        task = {
            "instance_id": raw["instance_id"],
            "repo": raw.get("repo", ""),
            "difficulty": raw.get("difficulty", ""),
            "difficulty_ord": difficulty_order.get(raw.get("difficulty", ""), -1),
            "fail_to_pass_count": len(fail_to_pass),
            "fail_test_file_count": len(fail_files),
            "pass_to_pass_count": len(pass_to_pass),
            "test_patch_hunks": test_patch["hunk_count"],
            "test_patch_changed_loc": test_patch["changed_loc"],
            **patch,
            **issue_features(raw.get("problem_statement", "")),
            "problem_statement": raw.get("problem_statement", ""),
        }
        tasks.append(task)
    return tasks


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def phase_summaries(path: Path) -> dict[tuple[str, str], dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(path):
        grouped[(row["agent"], row["instance_id"])].append(row)
    summaries: dict[tuple[str, str], dict[str, object]] = {}
    for key, segments in grouped.items():
        segments.sort(key=lambda row: int(row["subtask_index"]))
        pc = next((row for row in segments if row["subtask_code"] == "PC"), None)
        pv = next(
            (
                row
                for row in segments
                if row["subtask_code"] == "PV"
                and (pc is None or int(row["subtask_index"]) > int(pc["subtask_index"]))
            ),
            None,
        )
        refinements = [row for row in segments if row["subtask_code"] == "PR"]
        summaries[key] = {
            "first_pc_outcome": pc["local_outcome"] if pc else "missing",
            "first_pv_outcome": pv["local_outcome"] if pv else "missing",
            "pr_segment_count": len(refinements),
            "last_pr_outcome": refinements[-1]["local_outcome"] if refinements else "missing",
            "any_pr_plus": int(any(row["local_outcome"] == "+" for row in refinements)),
            "pc_paths": pc["paths"] if pc else "",
            "pr_paths": ";".join(row["paths"] for row in refinements if row["paths"]),
        }
    return summaries


def split_path(path: str) -> list[str]:
    return [part.strip() for part in str(path).split("->") if part.strip()]


def count_transition(sequence: list[str], left: str, right: str, stop_at_pc: bool = False) -> int:
    if stop_at_pc and "PC" in sequence:
        sequence = sequence[: sequence.index("PC")]
    return sum(a == left and b == right for a, b in zip(sequence, sequence[1:]))


def compact_path(sequence: list[str]) -> str:
    """Compress repeated FR-FL and PV-PR pairs while retaining order."""
    output: list[str] = []
    index = 0
    while index < len(sequence):
        if index + 1 < len(sequence) and sequence[index : index + 2] in (["FR", "FL"], ["PV", "PR"]):
            pair = tuple(sequence[index : index + 2])
            count = 0
            while index + 1 < len(sequence) and tuple(sequence[index : index + 2]) == pair:
                count += 1
                index += 2
            rendered = f"({' -> '.join(pair)})"
            if count > 1:
                rendered += f"^{count}"
            output.append(rendered)
            continue
        output.append(sequence[index])
        index += 1
    return " -> ".join(output)


def trajectory_features(row: dict[str, str]) -> dict[str, object]:
    sequence = split_path(row["canonical_path"])
    pre_loops = count_transition(sequence, "FR", "FL", stop_at_pc=True)
    post_loops = count_transition(sequence, "PV", "PR")
    has_pu = "PU" in sequence
    has_fl = "FL" in sequence
    if post_loops == 0:
        if not has_fl:
            core_route = "direct_patch"
        elif pre_loops <= 1:
            core_route = "focused_localization"
        else:
            core_route = "iterative_localization"
    elif post_loops == 1:
        core_route = "single_recovery"
    else:
        core_route = "iterative_recovery"
    return {
        **row,
        "resolved": int(row["resolved"]),
        "complete_repair": int(row["complete_repair"]),
        "distinct_subtask_types": int(row["distinct_subtask_types"]),
        "pre_loops": pre_loops,
        "post_loops": post_loops,
        "has_pu_path": int(has_pu),
        "has_fl_path": int(has_fl),
        "core_route": core_route,
        "compact_path": compact_path(sequence),
    }


def cramers_v(rows: list[dict[str, object]], feature: str, target: str) -> tuple[float, float]:
    x_values = sorted({str(row[feature]) for row in rows})
    y_values = sorted({str(row[target]) for row in rows})
    if len(x_values) < 2 or len(y_values) < 2:
        return 0.0, 1.0
    x_index = {value: index for index, value in enumerate(x_values)}
    y_index = {value: index for index, value in enumerate(y_values)}
    table = np.zeros((len(x_values), len(y_values)), dtype=int)
    for row in rows:
        table[x_index[str(row[feature])], y_index[str(row[target])]] += 1
    chi2, p_value, _, _ = chi2_contingency(table)
    n = table.sum()
    phi2 = chi2 / n
    rows_n, cols_n = table.shape
    correction = ((cols_n - 1) * (rows_n - 1)) / max(n - 1, 1)
    phi2_corrected = max(0.0, phi2 - correction)
    rows_corrected = rows_n - ((rows_n - 1) ** 2) / max(n - 1, 1)
    cols_corrected = cols_n - ((cols_n - 1) ** 2) / max(n - 1, 1)
    denominator = min(cols_corrected - 1, rows_corrected - 1)
    return (math.sqrt(phi2_corrected / denominator) if denominator > 0 else 0.0), p_value


def bin_task_features(task: dict[str, object]) -> dict[str, object]:
    changed = int(task["changed_loc"])
    hunks = int(task["hunk_count"])
    files = int(task["source_file_count"])
    return {
        **task,
        "multi_source": int(files > 1),
        "cross_parent": int(int(task["source_parent_count"]) > 1),
        "multi_hunk": int(hunks > 1),
        "large_patch": int(changed > 15),
        "broad_failure": int(int(task["fail_to_pass_count"]) > 1),
        "multi_fail_file": int(int(task["fail_test_file_count"]) > 1),
        "long_issue": int(int(task["statement_chars"]) > 1600),
    }


def candidate_task_class(task: dict[str, object]) -> str:
    """Mutually exclusive repair-topology class, defined without trajectories."""
    files = int(task["source_file_count"])
    parents = int(task["source_parent_count"])
    hunks = int(task["hunk_count"])
    if files > 1 and parents > 1:
        return "cross_component_coordination"
    if files > 1:
        return "intra_component_multifile"
    if hunks > 1:
        return "multisite_single_file"
    return "atomic_local"


def coarse_task_class(task_class: str) -> str:
    if task_class == "atomic_local":
        return "atomic_local"
    if task_class == "multisite_single_file":
        return "constraint_rich_single_file"
    return "distributed_multifile"


def cluster_fixed_effects(
    rows: list[dict[str, object]], baseline: str = "iterative_localization"
) -> list[dict[str, object]]:
    """Estimate within-instance route differences with agent fixed effects."""
    route_counts = Counter(str(row["core_route"]) for row in rows)
    routes = [route for route, count in route_counts.items() if count >= 5]
    if baseline not in routes:
        baseline = max(routes, key=route_counts.get)
    route_terms = [route for route in sorted(routes) if route != baseline]
    term_names = [f"route={route}" for route in route_terms] + ["agent=lingxi", "agent=moatless"]
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if str(row["core_route"]) in routes:
            grouped[str(row["instance_id"])].append(row)

    x_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    groups: list[str] = []
    for instance_id, group in grouped.items():
        if len(group) < 2 or len({str(row["core_route"]) for row in group}) < 2:
            continue
        raw_x = np.asarray(
            [
                [float(row["core_route"] == route) for route in route_terms]
                + [float(row["agent"] == "lingxi"), float(row["agent"] == "moatless")]
                for row in group
            ],
            dtype=float,
        )
        raw_y = np.asarray([float(row["resolved"]) for row in group], dtype=float)
        x_parts.append(raw_x - raw_x.mean(axis=0, keepdims=True))
        y_parts.append(raw_y - raw_y.mean())
        groups.extend([instance_id] * len(group))
    if not x_parts:
        return []

    x = np.vstack(x_parts)
    y = np.concatenate(y_parts)
    beta, _, rank, singular = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    bread = np.linalg.pinv(x.T @ x)
    meat = np.zeros((x.shape[1], x.shape[1]))
    group_array = np.asarray(groups)
    unique_groups = np.unique(group_array)
    for group in unique_groups:
        mask = group_array == group
        score = x[mask].T @ residual[mask]
        meat += np.outer(score, score)
    covariance = bread @ meat @ bread
    n, k = x.shape
    if len(unique_groups) > 1 and n > k:
        covariance *= (len(unique_groups) / (len(unique_groups) - 1)) * ((n - 1) / (n - k))
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    route_results = [
        {
            "route": baseline,
            "n": route_counts[baseline],
            "effect_vs_baseline": 0.0,
            "se": 0.0,
            "matched_instances": len(unique_groups),
            "rank": rank,
            "condition": float(singular[0] / singular[-1]) if len(singular) and singular[-1] > 0 else math.inf,
        }
    ]
    for index, route in enumerate(route_terms):
        route_results.append(
            {
                "route": route,
                "n": route_counts[route],
                "effect_vs_baseline": float(beta[index]),
                "se": float(standard_errors[index]),
                "matched_instances": len(unique_groups),
                "rank": rank,
                "condition": float(singular[0] / singular[-1]) if len(singular) and singular[-1] > 0 else math.inf,
            }
        )
    return sorted(route_results, key=lambda row: -float(row["effect_vs_baseline"]))


def matched_contrast(
    rows: list[dict[str, object]], left_routes: set[str], right_routes: set[str]
) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["instance_id"])].append(row)
    differences: list[float] = []
    for group in grouped.values():
        left = [int(row["resolved"]) for row in group if str(row["core_route"]) in left_routes]
        right = [int(row["resolved"]) for row in group if str(row["core_route"]) in right_routes]
        if left and right:
            differences.append(float(np.mean(left) - np.mean(right)))
    return {
        "matched_tasks": len(differences),
        "mean_difference": float(np.mean(differences)) if differences else float("nan"),
        "left_wins": sum(value > 0 for value in differences),
        "right_wins": sum(value < 0 for value in differences),
        "ties": sum(value == 0 for value in differences),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def fmt_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = [bin_task_features(task) for task in load_tasks()]
    task_by_id = {str(task["instance_id"]): task for task in tasks}
    trajectories = [trajectory_features(row) for row in read_csv(PRE12_DIR / "pre12_trajectories.csv")]
    complete = [row for row in trajectories if row["complete_repair"]]

    for task in tasks:
        task["candidate_class"] = candidate_task_class(task)
        task["coarse_class"] = coarse_task_class(str(task["candidate_class"]))

    phases = phase_summaries(PRE12_DIR / "pre12_subtasks.csv")
    enriched: list[dict[str, object]] = []
    for trajectory in complete:
        task = task_by_id[str(trajectory["instance_id"])]
        phase = phases.get((str(trajectory["agent"]), str(trajectory["instance_id"])), {})
        reference_files = {path for path in str(task["source_files"]).split(";") if path}
        pc_paths = {path for path in str(phase.get("pc_paths", "")).split(";") if path}
        pr_paths = {path for path in str(phase.get("pr_paths", "")).split(";") if path}
        pc_hits = reference_files & pc_paths
        final_hits = reference_files & (pc_paths | pr_paths)
        enriched.append(
            {
                **trajectory,
                **phase,
                "pc_reference_file_hits": len(pc_hits),
                "post_pr_reference_file_hits": len(final_hits),
                "pr_expanded_reference_scope": int(len(final_hits) > len(pc_hits)),
                **{key: value for key, value in task.items() if key != "problem_statement"},
            }
        )

    write_csv(OUT_DIR / "task_features.csv", [{key: value for key, value in row.items() if key != "problem_statement"} for row in tasks])
    write_csv(OUT_DIR / "trajectories_enriched.csv", enriched)

    report: list[str] = ["# RQ1.2 task-pathway exploration", ""]
    report.append("## Task feature distributions")
    for feature in [
        "observability",
        "source_file_count",
        "parent_count",
        "hunk_count",
        "changed_loc",
        "fail_to_pass_count",
        "fail_test_file_count",
        "difficulty",
        "candidate_class",
    ]:
        counts = Counter(str(task[feature]) for task in tasks)
        report.append(f"\n### {feature}\n")
        report.append(fmt_table([feature, "n", "share"], [[value, count, f"{count / len(tasks):.3f}"] for value, count in counts.most_common()]))

    report.append("\n## Outcome-blind feature association with pathway")
    association_rows: list[list[object]] = []
    binary_features = [
        "executable_evidence",
        "explicit_oracle",
        "multi_source",
        "cross_parent",
        "multi_hunk",
        "large_patch",
        "broad_failure",
        "multi_fail_file",
        "long_issue",
        "difficulty_ord",
    ]
    for agent in ["lingxi", "moatless", "openhands"]:
        subset = [row for row in enriched if row["agent"] == agent]
        for feature in binary_features:
            v_route, p_route = cramers_v(subset, feature, "core_route")
            v_distinct, p_distinct = cramers_v(subset, feature, "distinct_subtask_types")
            association_rows.append(
                [agent, feature, f"{v_route:.3f}", f"{p_route:.3g}", f"{v_distinct:.3f}", f"{p_distinct:.3g}"]
            )
    association_rows.sort(key=lambda row: (row[0], -float(row[2])))
    report.append(
        fmt_table(
            ["agent", "task feature", "V(route)", "p", "V(distinct)", "p"],
            association_rows,
        )
    )

    report.append("\n## Candidate task classes")
    class_rows: list[list[object]] = []
    for task_class, task_count in Counter(str(task["candidate_class"]) for task in tasks).most_common():
        class_tasks = [task for task in tasks if task["candidate_class"] == task_class]
        class_trajectories = [row for row in enriched if row["candidate_class"] == task_class]
        class_rows.append(
            [
                task_class,
                task_count,
                f"{np.mean([int(task['difficulty_ord']) for task in class_tasks]):.2f}",
                f"{np.mean([int(task['source_file_count']) for task in class_tasks]):.2f}",
                f"{np.mean([int(task['hunk_count']) for task in class_tasks]):.2f}",
                f"{np.mean([int(task['changed_loc']) for task in class_tasks]):.1f}",
                f"{np.mean([int(task['fail_to_pass_count']) for task in class_tasks]):.2f}",
                f"{np.mean([int(task['executable_evidence']) for task in class_tasks]):.2f}",
                f"{np.mean([int(row['distinct_subtask_types']) for row in class_trajectories]):.2f}",
                f"{np.mean([int(row['post_loops']) for row in class_trajectories]):.2f}",
            ]
        )
    report.append(
        fmt_table(
            ["class", "tasks", "difficulty", "files", "hunks", "LOC", "F2P", "executable", "distinct", "post loops"],
            class_rows,
        )
    )

    report.append("\n## Class x agent dominant structures")
    dominant_rows: list[list[object]] = []
    for task_class in sorted({str(task["candidate_class"]) for task in tasks}):
        for agent in ["lingxi", "moatless", "openhands"]:
            subset = [row for row in enriched if row["candidate_class"] == task_class and row["agent"] == agent]
            distinct = Counter(int(row["distinct_subtask_types"]) for row in subset)
            routes = Counter(str(row["core_route"]) for row in subset)
            paths = Counter(str(row["compact_path"]) for row in subset)
            top_distinct, top_distinct_n = distinct.most_common(1)[0]
            top_route, top_route_n = routes.most_common(1)[0]
            top_path, top_path_n = paths.most_common(1)[0]
            dominant_rows.append(
                [
                    task_class,
                    agent,
                    len(subset),
                    f"{top_distinct} ({top_distinct_n / len(subset):.2f})",
                    f"{top_route} ({top_route_n / len(subset):.2f})",
                    f"{top_path} ({top_path_n / len(subset):.2f})",
                ]
            )
    report.append(fmt_table(["class", "agent", "n", "modal distinct", "modal route", "modal exact path"], dominant_rows))

    report.append("\n## Class x route raw outcomes")
    outcome_rows: list[list[object]] = []
    for task_class in sorted({str(task["candidate_class"]) for task in tasks}):
        for route in ["direct_patch", "focused_localization", "iterative_localization", "single_recovery", "iterative_recovery"]:
            subset = [row for row in enriched if row["candidate_class"] == task_class and row["core_route"] == route]
            if len(subset) < 5:
                continue
            outcome_rows.append(
                [task_class, route, len(subset), f"{np.mean([int(row['resolved']) for row in subset]):.3f}"]
            )
    report.append(fmt_table(["class", "route", "n", "raw RR"], outcome_rows))

    report.append("\n## Task scope and reactive pathway formation")
    formation_rows: list[list[object]] = []
    for task_class in sorted({str(task["candidate_class"]) for task in tasks}):
        subset = [row for row in enriched if row["candidate_class"] == task_class]
        pc_plus = np.mean([row.get("first_pc_outcome") == "+" for row in subset])
        pv_minus = np.mean([row.get("first_pv_outcome") == "-" for row in subset])
        entered_pr = np.mean([int(row.get("pr_segment_count", 0)) > 0 for row in subset])
        no_pr = [row for row in subset if int(row.get("pr_segment_count", 0)) == 0]
        pre_mean = np.mean([int(row["pre_loops"]) for row in no_pr]) if no_pr else float("nan")
        formation_rows.append(
            [task_class, len(subset), f"{pc_plus:.3f}", f"{pv_minus:.3f}", f"{entered_pr:.3f}", f"{pre_mean:.2f}"]
        )
    report.append(
        fmt_table(
            ["class", "trajectories", "first PC+", "first PV-", "entered PR", "pre loops if no PR"],
            formation_rows,
        )
    )

    report.append("\n## Coarse-class route performance")
    coarse_outcomes: list[list[object]] = []
    for task_class in ["atomic_local", "constraint_rich_single_file", "distributed_multifile"]:
        class_rows_raw = [row for row in enriched if row["coarse_class"] == task_class]
        fixed_effects = cluster_fixed_effects(class_rows_raw)
        for result in fixed_effects:
            subset = [row for row in class_rows_raw if row["core_route"] == result["route"]]
            raw_rate = np.mean([int(row["resolved"]) for row in subset])
            coarse_outcomes.append(
                [
                    task_class,
                    result["route"],
                    result["n"],
                    f"{raw_rate:.3f}",
                    f"{float(result['effect_vs_baseline']):+.3f}",
                    f"{float(result['se']):.3f}",
                    result["matched_instances"],
                ]
            )
    report.append(
        fmt_table(
            ["class", "route", "n", "raw RR", "within-instance effect", "cluster SE", "matched tasks"],
            coarse_outcomes,
        )
    )

    report.append("\n## Matched pathway contrasts")
    contrast_rows: list[list[object]] = []
    no_recovery = {"direct_patch", "focused_localization", "iterative_localization"}
    contrast_definitions = [
        ("no recovery - single recovery", no_recovery, {"single_recovery"}),
        ("no recovery - iterative recovery", no_recovery, {"iterative_recovery"}),
        ("focused - iterative localization", {"focused_localization"}, {"iterative_localization"}),
    ]
    for task_class in ["atomic_local", "constraint_rich_single_file", "distributed_multifile"]:
        class_rows_raw = [row for row in enriched if row["coarse_class"] == task_class]
        for label, left, right in contrast_definitions:
            result = matched_contrast(class_rows_raw, left, right)
            contrast_rows.append(
                [
                    task_class,
                    label,
                    result["matched_tasks"],
                    f"{float(result['mean_difference']):+.3f}",
                    result["left_wins"],
                    result["right_wins"],
                    result["ties"],
                ]
            )
    report.append(
        fmt_table(
            ["class", "contrast", "matched tasks", "mean left-right", "left wins", "right wins", "ties"],
            contrast_rows,
        )
    )

    report.append("\n## Recovery by task class and first PC outcome")
    recovery_rows: list[list[object]] = []
    for task_class in ["atomic_local", "constraint_rich_single_file", "distributed_multifile"]:
        for pc_outcome in ["+", "-"]:
            subset = [
                row
                for row in enriched
                if row["coarse_class"] == task_class and row.get("first_pc_outcome") == pc_outcome
            ]
            for recovery, routes in [
                ("none", no_recovery),
                ("single", {"single_recovery"}),
                ("iterative", {"iterative_recovery"}),
            ]:
                cells = [row for row in subset if row["core_route"] in routes]
                if not cells:
                    continue
                recovery_rows.append(
                    [
                        task_class,
                        f"PC{pc_outcome}",
                        recovery,
                        len(cells),
                        f"{np.mean([int(row['resolved']) for row in cells]):.3f}",
                    ]
                )
    report.append(fmt_table(["class", "first PC", "recovery", "n", "raw RR"], recovery_rows))

    report.append("\n## Refinement mechanism checks")
    mechanism_rows: list[list[object]] = []
    for task_class in ["atomic_local", "constraint_rich_single_file", "distributed_multifile"]:
        subset = [row for row in enriched if row["coarse_class"] == task_class]
        for recovery, predicate in [
            ("single", lambda row: int(row["post_loops"]) == 1),
            ("iterative", lambda row: int(row["post_loops"]) >= 2),
        ]:
            cells = [row for row in subset if predicate(row)]
            if not cells:
                continue
            mechanism_rows.append(
                [
                    task_class,
                    recovery,
                    len(cells),
                    f"{np.mean([int(row.get('any_pr_plus', 0)) for row in cells]):.3f}",
                    f"{np.mean([row.get('last_pr_outcome') == '+' for row in cells]):.3f}",
                    f"{np.mean([int(row.get('pr_expanded_reference_scope', 0)) for row in cells]):.3f}",
                    f"{np.mean([int(row['resolved']) for row in cells]):.3f}",
                ]
            )
    report.append(
        fmt_table(
            ["class", "recovery", "n", "any PR+", "last PR+", "expanded ref scope", "RR"],
            mechanism_rows,
        )
    )

    (OUT_DIR / "exploration.md").write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(OUT_DIR / "exploration.md")


if __name__ == "__main__":
    main()
