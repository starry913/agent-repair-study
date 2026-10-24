#!/usr/bin/env python3
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "data" / "processed" / "rq1"
OUT_DIR = ROOT / "data" / "processed" / "rq1_deep"

CODE = {
    "Problem Understanding": "PU",
    "Failure Reproduction": "FR",
    "Fault Localization": "FL",
    "Patch Construction": "PC",
    "Patch Refinement": "PR",
    "Patch Validation": "PV",
}

OUTCOME = {
    "scope-formed": "+",
    "no-scope": "-",
    "failure-reproduced": "+",
    "not-reproduced": "-",
    "inconclusive": "?",
    "blocked": "?",
    "target-located": "+",
    "no-target": "-",
    "patch-applied": "+",
    "edit-blocked": "-",
    "pass": "+",
    "fail": "-",
}


def read_csv(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def rate(rows):
    n = len(rows)
    res = sum(int(r["resolved"]) for r in rows)
    return n, res, res / n if n else 0.0


def summarize(items, keys):
    buckets = defaultdict(list)
    for item in items:
        buckets[tuple(item[k] for k in keys)].append(item)
    rows = []
    for key, vals in sorted(buckets.items()):
        n, res, rr = rate(vals)
        row = {k: v for k, v in zip(keys, key)}
        row.update({"n": n, "resolved": res, "resolved_rate": f"{rr:.3f}"})
        rows.append(row)
    return rows


def loop_bin(n):
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 3:
        return "2-3"
    if n <= 7:
        return "4-7"
    return "8+"


def pre_loop_bin(n):
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 2:
        return "2"
    if n <= 4:
        return "3-4"
    return "5+"


def md_table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return lines


def compress_path(seq):
    return " -> ".join(seq)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subtask_rows = read_csv(IN_DIR / "rq1_subtasks.csv")
    traj_rows = read_csv(IN_DIR / "rq1_trajectories.csv")
    complete = {
        (r["agent"], r["instance_id"]): r
        for r in traj_rows
        if int(r["complete_repair"])
    }

    by_traj = defaultdict(list)
    for r in subtask_rows:
        key = (r["agent"], r["instance_id"])
        if key in complete:
            by_traj[key].append(r)

    traj_features = []
    pv_events = []
    edge_events = []

    for key, rows in by_traj.items():
        rows = sorted(rows, key=lambda r: int(r["subtask_index"]))
        seq = [CODE[r["subtask_type"]] for r in rows]
        resolved = int(rows[0]["resolved"])
        agent, instance_id = key
        first_pc = next((i for i, x in enumerate(seq) if x == "PC"), len(seq))
        pre_seq = seq[:first_pc]
        post_seq = seq[first_pc:]
        pre_edges = list(zip(pre_seq, pre_seq[1:]))
        post_edges = list(zip(post_seq, post_seq[1:]))
        fl_fr = sum(1 for a, b in pre_edges if a == "FL" and b == "FR")
        fr_fl = sum(1 for a, b in pre_edges if a == "FR" and b == "FL")
        pv_pr = sum(1 for a, b in post_edges if a == "PV" and b == "PR")
        pr_pv = sum(1 for a, b in post_edges if a == "PR" and b == "PV")

        first_fr = next((i for i, x in enumerate(seq) if x == "FR"), None)
        first_fl = next((i for i, x in enumerate(seq) if x == "FL"), None)
        if first_fr is None and first_fl is None:
            order = "neither FR nor FL"
        elif first_fr is None:
            order = "FL only"
        elif first_fl is None:
            order = "FR only"
        elif first_fl < first_fr:
            order = "FL before FR"
        else:
            order = "FR before FL"

        traj_features.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": resolved,
                "path": compress_path(seq),
                "first_fr_fl_order": order,
                "fl_fr_loops": fl_fr,
                "fr_fl_loops": fr_fl,
                "pv_pr_loops": pv_pr,
                "pr_pv_loops": pr_pv,
                "fl_fr_bin": pre_loop_bin(fl_fr),
                "pv_pr_bin": loop_bin(pv_pr),
                "pre_loop_bin": pre_loop_bin(fl_fr),
                "post_loop_bin": loop_bin(pv_pr),
                "has_pre_loop": int(fl_fr > 0),
                "has_post_loop": int(pv_pr > 0),
                "has_both_loop_types": int(fl_fr > 0 and pv_pr > 0),
                "has_only_pre_loop": int(fl_fr > 0 and pv_pr == 0),
                "has_only_post_loop": int(fl_fr == 0 and pv_pr > 0),
                "has_no_loops": int(fl_fr == 0 and pv_pr == 0),
            }
        )

        for i, r in enumerate(rows):
            cur = CODE[r["subtask_type"]]
            nxt = CODE[rows[i + 1]["subtask_type"]] if i + 1 < len(rows) else "END"
            edge_events.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": resolved,
                    "edge": f"{cur}->{nxt}",
                    "from": cur,
                    "to": nxt,
                }
            )
            if cur == "PV":
                local = OUTCOME.get(r["local_outcome"], "?")
                pv_events.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "resolved": resolved,
                        "pv_outcome": local,
                        "next": nxt,
                        "pv_outcome_next": f"PV{local}->{nxt}",
                    }
                )

    # Tables.
    rows = []
    for name in ["has_no_loops", "has_only_pre_loop", "has_only_post_loop", "has_both_loop_types"]:
        vals = [r for r in traj_features if int(r[name])]
        n, res, rr = rate(vals)
        rows.append({"pattern": name, "n": n, "resolved": res, "resolved_rate": f"{rr:.3f}"})
    write_csv(OUT_DIR / "loop_type_presence.csv", rows)

    write_csv(OUT_DIR / "pre_loop_bins.csv", summarize(traj_features, ["fl_fr_bin"]))
    write_csv(OUT_DIR / "post_loop_bins.csv", summarize(traj_features, ["pv_pr_bin"]))
    write_csv(OUT_DIR / "loop_cross_table.csv", summarize(traj_features, ["pre_loop_bin", "post_loop_bin"]))
    write_csv(OUT_DIR / "first_fr_fl_order.csv", summarize(traj_features, ["first_fr_fl_order"]))
    write_csv(OUT_DIR / "pv_feedback_next.csv", summarize(pv_events, ["pv_outcome", "next"]))
    write_csv(OUT_DIR / "pv_feedback_next_agent.csv", summarize(pv_events, ["agent", "pv_outcome", "next"]))

    edge_summary = summarize(edge_events, ["edge"])
    edge_summary = sorted(edge_summary, key=lambda r: int(r["n"]), reverse=True)
    write_csv(OUT_DIR / "edge_summary.csv", edge_summary)
    write_csv(OUT_DIR / "trajectory_deep_features.csv", traj_features)

    report = []
    report.append("# RQ1 Deep Dive\n")

    report.append("## Loop Type Presence\n")
    report.extend(md_table(rows, ["pattern", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## Pre-patch Loop Bins: FL -> FR\n")
    pre_rows = summarize(traj_features, ["fl_fr_bin"])
    order = {"0": 0, "1": 1, "2": 2, "3-4": 3, "5+": 4}
    pre_rows = sorted(pre_rows, key=lambda r: order[r["fl_fr_bin"]])
    report.extend(md_table(pre_rows, ["fl_fr_bin", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## Post-patch Loop Bins: PV -> PR\n")
    post_rows = summarize(traj_features, ["pv_pr_bin"])
    order = {"0": 0, "1": 1, "2-3": 2, "4-7": 3, "8+": 4}
    post_rows = sorted(post_rows, key=lambda r: order[r["pv_pr_bin"]])
    report.extend(md_table(post_rows, ["pv_pr_bin", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## Cross Table: Pre-loop vs Post-loop\n")
    cross = summarize(traj_features, ["pre_loop_bin", "post_loop_bin"])
    cross = sorted(cross, key=lambda r: ({"0": 0, "1": 1, "2": 2, "3-4": 3, "5+": 4}[r["pre_loop_bin"]], {"0": 0, "1": 1, "2-3": 2, "4-7": 3, "8+": 4}[r["post_loop_bin"]]))
    report.extend(md_table(cross, ["pre_loop_bin", "post_loop_bin", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## First FR/FL Order\n")
    report.extend(md_table(summarize(traj_features, ["first_fr_fl_order"]), ["first_fr_fl_order", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## PV Feedback and Next State\n")
    pv_next = summarize(pv_events, ["pv_outcome", "next"])
    pv_next = sorted(pv_next, key=lambda r: (r["pv_outcome"], r["next"]))
    report.extend(md_table(pv_next, ["pv_outcome", "next", "n", "resolved", "resolved_rate"]))
    report.append("")

    (OUT_DIR / "rq1_deep_report.md").write_text("\n".join(report), encoding="utf-8")
    print(OUT_DIR / "rq1_deep_report.md")


if __name__ == "__main__":
    main()
