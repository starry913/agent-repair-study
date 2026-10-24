#!/usr/bin/env python3
import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "processed" / "rq1" / "rq1_subtasks.csv"
OUT = ROOT / "data" / "processed" / "rq2_probe"

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


def read_rows():
    with IN.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def summarize(rows, keys):
    c = defaultdict(lambda: [0, 0])
    for r in rows:
        key = tuple(r[k] for k in keys)
        c[key][0] += 1
        c[key][1] += int(r["resolved"])
    out = []
    for key, (n, resolved) in sorted(c.items()):
        row = {k: v for k, v in zip(keys, key)}
        row["n"] = n
        row["resolved"] = resolved
        row["resolved_rate"] = f"{resolved / n:.3f}"
        out.append(row)
    return out


def md_table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return lines


def main():
    rows = read_rows()
    by = defaultdict(list)
    for r in rows:
        by[(r["agent"], r["instance_id"])].append(r)

    trans = []
    triads = []
    for (agent, instance_id), rs in by.items():
        rs = sorted(rs, key=lambda x: int(x["subtask_index"]))
        seq = [
            {
                "type": CODE[r["subtask_type"]],
                "outcome": OUTCOME.get(r["local_outcome"], "?"),
                "resolved": int(r["resolved"]),
                "agent": agent,
                "instance_id": instance_id,
            }
            for r in rs
        ]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            trans.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": a["resolved"],
                    "from_type": a["type"],
                    "from_o": a["outcome"],
                    "to_type": b["type"],
                    "to_o": b["outcome"],
                    "edge": f"{a['type']}->{b['type']}",
                    "oo": f"{a['outcome']}->{b['outcome']}",
                }
            )
        for i in range(len(seq) - 2):
            a, b, c = seq[i], seq[i + 1], seq[i + 2]
            if a["type"] == "PV" and b["type"] == "PR" and c["type"] == "PV":
                triads.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "resolved": a["resolved"],
                        "pv1": a["outcome"],
                        "pr": b["outcome"],
                        "pv2": c["outcome"],
                        "pattern": f"PV{a['outcome']}->PR{b['outcome']}->PV{c['outcome']}",
                    }
                )

    outputs = {}
    outputs["fr_outcome_to_next_type.csv"] = summarize(
        [r for r in trans if r["from_type"] == "FR"], ["from_o", "to_type"]
    )
    outputs["fl_outcome_to_next_type.csv"] = summarize(
        [r for r in trans if r["from_type"] == "FL"], ["from_o", "to_type"]
    )
    outputs["pv_outcome_to_next_type.csv"] = summarize(
        [r for r in trans if r["from_type"] == "PV"], ["from_o", "to_type"]
    )
    outputs["fr_to_fl_outcome.csv"] = summarize(
        [r for r in trans if r["from_type"] == "FR" and r["to_type"] == "FL"],
        ["from_o", "to_o"],
    )
    outputs["fl_to_fr_outcome.csv"] = summarize(
        [r for r in trans if r["from_type"] == "FL" and r["to_type"] == "FR"],
        ["from_o", "to_o"],
    )
    outputs["pv_to_pr_or_end.csv"] = summarize(
        [r for r in trans if r["from_type"] == "PV" and r["to_type"] in {"PR", "END"}],
        ["from_o", "to_type"],
    )
    outputs["pv_pr_pv_triads.csv"] = summarize(triads, ["pv1", "pv2"])
    outputs["pv_pr_pv_patterns.csv"] = summarize(triads, ["pattern"])
    outputs["outcome_propagation.csv"] = summarize(trans, ["oo"])
    outputs["typed_transition_outcomes.csv"] = summarize(
        trans, ["from_type", "from_o", "to_type", "to_o"]
    )

    for name, data in outputs.items():
        write_csv(name, data)

    report = ["# RQ2 Probe\n"]
    for title, name, cols in [
        ("FR outcome -> next subtask", "fr_outcome_to_next_type.csv", ["from_o", "to_type", "n", "resolved", "resolved_rate"]),
        ("FL outcome -> next subtask", "fl_outcome_to_next_type.csv", ["from_o", "to_type", "n", "resolved", "resolved_rate"]),
        ("PV outcome -> next subtask", "pv_outcome_to_next_type.csv", ["from_o", "to_type", "n", "resolved", "resolved_rate"]),
        ("FR -> FL outcome relation", "fr_to_fl_outcome.csv", ["from_o", "to_o", "n", "resolved", "resolved_rate"]),
        ("FL -> FR outcome relation", "fl_to_fr_outcome.csv", ["from_o", "to_o", "n", "resolved", "resolved_rate"]),
        ("PV -> PR -> PV triads", "pv_pr_pv_triads.csv", ["pv1", "pv2", "n", "resolved", "resolved_rate"]),
        ("Outcome propagation", "outcome_propagation.csv", ["oo", "n", "resolved", "resolved_rate"]),
    ]:
        report.append(f"## {title}\n")
        report.extend(md_table(outputs[name], cols))
        report.append("")

    (OUT / "rq2_probe_report.md").write_text("\n".join(report), encoding="utf-8")
    print(OUT / "rq2_probe_report.md")


if __name__ == "__main__":
    main()
