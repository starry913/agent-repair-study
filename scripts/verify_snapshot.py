#!/usr/bin/env python3
"""Validate the published research snapshot without third-party dependencies.

Checks distinguish trajectory-, subtask-, and transition-level denominators.
This is a consistency audit, not a semantic validation of annotation rules.
"""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "pre/pre-12"
RQ2 = ROOT / "RQ2/data/pro"


def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def check(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def key(row):
    return row["agent"], row["instance_id"]


def main():
    trajectories = rows(PRE / "dataset/pre12_trajectories.csv")
    subtasks = rows(PRE / "dataset/pre12_subtasks.csv")
    actions = rows(PRE / "dataset/pre12_actions.csv")
    check(len(trajectories) == 1500, "trajectory count")
    check(len(subtasks) == 21142, "subtask count")
    check(len(actions) == 155836, "action count")
    check(len({key(r) for r in trajectories}) == 1500, "unique agent-instance keys")
    by_key = {key(r): r for r in trajectories}
    action_counts = Counter(key(r) for r in actions)
    subtask_counts = Counter(key(r) for r in subtasks)
    check(set(action_counts) <= set(by_key), "action keys exist in trajectory table")
    check(set(subtask_counts) <= set(by_key), "subtask keys exist in trajectory table")
    for r in trajectories:
        check(action_counts[key(r)] == int(r["n_events"]), f"action count for {key(r)}")
        check(subtask_counts[key(r)] == int(r["n_subtasks"]), f"subtask count for {key(r)}")
    for r in actions + subtasks:
        check(r["resolved"] == by_key[key(r)]["resolved"], f"joined outcome for {key(r)}")

    official = ROOT / "swe_verified_claude4_traj/data/official/results"
    for agent, expected in [("lingxi", 373), ("moatless", 354), ("openhands", 352)]:
        selected = [r for r in trajectories if r["agent"] == agent]
        resolved = set(json.loads((official / f"{agent}.json").read_text())["resolved"])
        check(len(selected) == 500, f"{agent} sample size")
        check(sum(int(r["resolved"]) for r in selected) == expected, f"{agent} resolution count")
        check(all(bool(int(r["resolved"])) == (r["instance_id"] in resolved) for r in selected),
              f"{agent} official outcome agreement")

    complete = [r for r in trajectories if r["complete_repair"] == "1"]
    check(len(complete) == 1491, "complete trajectory count")
    check(sum(int(r["resolved"]) for r in trajectories) == 1079, "total resolved")
    for r in subtasks:
        check(r["local_outcome"] in {"+", "-", "?"}, "valid local outcome")
        if r["subtask_code"] == "PR":
            check(int(r["n_diagnostic_artifacts"]) == 0, "PR excludes diagnostic artifacts")
            check(int(r["n_product_source_edits"]) > 0, "PR contains product-source edit")

    # Independently reconstruct RQ2 denominators from ordered subtasks.
    grouped = defaultdict(list)
    for r in subtasks:
        grouped[key(r)].append(r)
    counts = Counter()
    transition_counts = {"FR_to_FL": Counter(), "PV_to_PR": Counter(),
                         "latest_FL_to_first_PC": Counter()}
    for seq in grouped.values():
        seq.sort(key=lambda r: int(r["subtask_index"]))
        for a, b in zip(seq, seq[1:]):
            name = f'{a["subtask_code"]}_to_{b["subtask_code"]}'
            if name in {"FR_to_FL", "PV_to_PR"}:
                counts[name] += 1
                transition_counts[name][a["local_outcome"], b["local_outcome"]] += 1
        for a, b, c in zip(seq, seq[1:], seq[2:]):
            if [r["subtask_code"] for r in (a, b, c)] == ["PV", "PR", "PV"]:
                counts["PV_PR_PV"] += 1
        latest_fl = None
        for r in seq:
            if r["subtask_code"] == "FL":
                latest_fl = r
            if r["subtask_code"] == "PC":
                if latest_fl is not None:
                    counts["latest_FL_to_first_PC"] += 1
                    transition_counts["latest_FL_to_first_PC"][latest_fl["local_outcome"], r["local_outcome"]] += 1
                break
    expected = {"FR_to_FL": 6287, "PV_to_PR": 1683,
                "latest_FL_to_first_PC": 1425, "PV_PR_PV": 1673}
    check(dict(counts) == expected, "reconstructed RQ2 denominators")
    for name, filename in [("FR_to_FL", "rq21_fr_fl_transitions.csv"),
                           ("PV_to_PR", "rq23_pv_pr_transitions.csv"),
                           ("latest_FL_to_first_PC", "rq22_latest_fl_first_pc.csv")]:
        table = {(r["source_outcome"], r["target_outcome"]): int(r["n"])
                 for r in rows(RQ2 / filename) if r["agent"] == "total"}
        check(table == dict(transition_counts[name]), f"recomputed transition table: {name}")

    # Verify F1 directly from local records, rather than copied summary text.
    pc = {}
    for outcome, expected_counts in [("+", (1365, 1029)), ("-", (127, 50))]:
        selected = [r for r in subtasks if r["subtask_code"] == "PC" and r["local_outcome"] == outcome]
        actual = len(selected), sum(int(r["resolved"]) for r in selected)
        check(actual == expected_counts, f"F1 PC{outcome} counts")
        pc[outcome] = round(actual[1] / actual[0] * 100, 1)

    # Verify F3 against trajectory-level loop counts.
    loop_stats = {}
    for band in [0, 1, 5]:
        selected = [r for r in complete if (int(r["validation_refinement_loops"]) >= 5
                    if band == 5 else int(r["validation_refinement_loops"]) == band)]
        loop_stats[str(band)] = [len(selected), round(sum(int(r["resolved"]) for r in selected) / len(selected) * 100, 1)]
    check(loop_stats == {"0": [949, 78.2], "1": [238, 69.3], "5": [110, 49.1]}, "F3 loop counts and rates")

    mechanisms = [r for r in rows(RQ2 / "rq23_pv_plus_pr_plus_mechanisms.csv") if r["agent"] == "total"]
    n = sum(int(r["n"]) for r in mechanisms)
    last_fail = sum(int(r["n"]) for r in mechanisms if r["mechanism"].startswith(("fail_only__", "mixed_last_fail__")))
    existing = sum(int(r["n"]) for r in mechanisms if r["mechanism"].endswith("__existing_file"))
    check((n, last_fail, existing) == (271, 195, 258), "F6 feedback and edit-scope counts")

    for filename in ["pre12_actions.csv", "pre12_subtasks.csv", "pre12_trajectories.csv"]:
        a = (PRE / "dataset" / filename).read_bytes()
        b = (ROOT / "swe_verified_claude4_traj/data/processed/pre12" / filename).read_bytes()
        check(hashlib.sha256(a).digest() == hashlib.sha256(b).digest(), f"curated/generated snapshot agreement: {filename}")
    print("PASS: corpus counts, table joins, official labels, PR boundaries, and snapshot agreement")
    print("PASS: independently reconstructed RQ2 transitions", dict(counts))
    print("PASS: PC resolution percentages", pc)
    print("PASS: post-patch loop sample sizes and resolution percentages", loop_stats)
    print(f"PASS: PV+ -> PR+ last-failure share {last_fail/n:.1%}; existing-file share {existing/n:.1%}")


if __name__ == "__main__":
    main()
