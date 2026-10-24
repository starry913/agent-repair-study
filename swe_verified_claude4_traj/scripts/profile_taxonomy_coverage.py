#!/usr/bin/env python3
import argparse
import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ACTIONS = ["Understand", "Read", "Search", "Execute", "Create", "Modify", "Delete", "Setup"]
EDIT_ACTIONS = {"Create", "Modify", "Delete"}


def load_outcomes(root: Path):
    outcomes = {}
    for agent in ["lingxi", "moatless", "openhands"]:
        path = root / "data" / "official" / "results" / f"{agent}.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        resolved = set(obj.get("resolved", []))
        outcomes[agent] = resolved
    return outcomes


def text_from_content(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(text_from_content(item["content"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, dict):
        return "\n".join(text_from_content(v) for v in content.values())
    return str(content)


def parse_json_args(s):
    if not isinstance(s, str):
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def classify_command(command: str):
    c = (command or "").lower()
    if not c.strip():
        return "Execute"
    setup_patterns = [
        r"\bpip\s+install\b",
        r"\bconda\s+",
        r"\bnpm\s+install\b",
        r"\bapt(-get)?\s+",
        r"\bpoetry\s+install\b",
        r"\bexport\s+",
        r"\bchmod\s+",
        r"\bmkdir\b",
        r"\bgit\s+(checkout|clone|submodule|config)\b",
    ]
    if any(re.search(p, c) for p in setup_patterns):
        return "Setup"
    if re.search(r"\brm\s+|unlink|delete", c):
        return "Delete"
    if re.search(r"\bsed\s+-i\b|apply_patch|patch\s+|python\s+- <<|python3\s+- <<|perl\s+-pi|str_replace", c):
        return "Modify"
    if re.search(r"\btouch\b|cat\s+>|tee\s+|printf\s+.*>", c):
        return "Create"
    if re.search(r"\b(rg|grep|find|git\s+grep)\b", c):
        return "Search"
    if re.search(r"\b(cat|sed\s+-n|head|tail|ls|tree|pwd)\b", c):
        return "Read"
    return "Execute"


def classify_lingxi_action(line: str):
    s = (line or "").strip()
    low = s.lower()
    name = re.split(r"[\(\{]", s, 1)[0].strip()
    if name == "think" or low.startswith("think("):
        return "Understand", name or "think"
    if name == "ask_repository_agent" or "ask_repository_agent" in low:
        return "Search", name or "ask_repository_agent"
    if name == "str_replace_based_edit_tool" or "str_replace_based_edit_tool" in low:
        command = ""
        m = re.search(r"str_replace_based_edit_tool\((.*)\)\s*$", s)
        if m:
            try:
                args = ast.literal_eval(m.group(1))
                if isinstance(args, dict):
                    command = str(args.get("command", "")).lower()
            except Exception:
                command = ""
        if command == "view":
            return "Read", f"{name}.view"
        if command == "create":
            return "Create", f"{name}.create"
        if command in {"str_replace", "insert", "undo_edit"}:
            return "Modify", f"{name}.{command}"
        return "Modify", f"{name}.{command or 'unknown'}"
    if name == "bash" or low.startswith("bash("):
        command = ""
        m = re.search(r"bash\((.*)\)\s*$", s)
        if m:
            try:
                args = ast.literal_eval(m.group(1))
                if isinstance(args, dict):
                    command = str(args.get("command", ""))
            except Exception:
                command = ""
        return classify_command(command), name or "bash"
    if "search" in low or "grep" in low or "find" in low:
        return "Search", name or "unknown"
    if any(x in low for x in ["view", "read", "open", "list", "show_file", "cat"]):
        return "Read", name or "unknown"
    if any(x in low for x in ["run", "execute", "pytest", "test", "python", "bash"]):
        return "Execute", name or "unknown"
    if any(x in low for x in ["create", "write_new", "new_file"]):
        return "Create", name or "unknown"
    if any(x in low for x in ["delete", "remove"]):
        return "Delete", name or "unknown"
    if any(x in low for x in ["edit", "modify", "replace", "patch", "insert"]):
        return "Modify", name or "unknown"
    if any(x in low for x in ["install", "setup", "mkdir", "chmod", "configure"]):
        return "Setup", name or "unknown"
    return "Execute", name or "unknown"


def moatless_action_class(action):
    cls = ""
    if isinstance(action, dict):
        cls = str(action.get("action_args_class") or action.get("name") or "")
    cls = cls.split(".")[-1]
    return cls or "unknown"


def classify_moatless_action(action, output_text=""):
    name = moatless_action_class(action)
    low = name.lower()
    if "cleanupcontext" in low:
        return "Setup", name
    if "semanticsearch" in low or "greptool" in low or "glob" in low or "find" in low or "search" in low:
        return "Search", name
    if "readfile" in low or "listfiles" in low or "view" in low or "show" in low:
        return "Read", name
    if "create" in low:
        return "Create", name
    if "delete" in low or "remove" in low or "cleanup" in low:
        return "Delete", name
    if "edit" in low or "replace" in low or "append" in low or "insert" in low or "patch" in low:
        return "Modify", name
    if "runtests" in low or "run" in low or "execute" in low or "python" in low:
        return "Execute", name
    if "finish" in low:
        return "Understand", name
    if "setup" in low or "install" in low:
        return "Setup", name
    return classify_command(output_text), name


def classify_openhands_tool(name, args):
    name = name or "unknown"
    low = name.lower()
    if low == "think":
        return "Understand", name
    if low in {"execute_bash", "bash"}:
        return classify_command(args.get("command", "")), name
    if low in {"str_replace_editor", "file_editor"}:
        cmd = str(args.get("command", "")).lower()
        if cmd == "view":
            return "Read", f"{name}.view"
        if cmd == "create":
            return "Create", f"{name}.create"
        if cmd in {"str_replace", "insert", "undo_edit"}:
            return "Modify", f"{name}.{cmd}"
        return "Modify", f"{name}.{cmd or 'unknown'}"
    if "search" in low:
        return "Search", name
    if "read" in low or "view" in low:
        return "Read", name
    if "delete" in low or "remove" in low:
        return "Delete", name
    if "create" in low:
        return "Create", name
    if "edit" in low or "replace" in low or "patch" in low:
        return "Modify", name
    return "Execute", name


def execute_outcome(text, command="", structured=False):
    low = (text or "").lower()
    command_low = (command or "").lower()
    if not low.strip():
        return "unknown"

    # Test-runner summaries are stronger than individual words in logs.  In
    # particular, "78 passed, 0 failed" must not be classified as a failure.
    negative_counts = [
        int(value)
        for value in re.findall(r"\b(\d+)\s+(?:failed|failures?|errors?)\b", low)
    ]
    negative_counts += [
        int(value)
        for value in re.findall(r"\b(?:failed|failures?|errors?)\s*[:=]\s*(\d+)\b", low)
    ]
    positive_counts = [
        int(value)
        for value in re.findall(r"\b(\d+)\s+(?:passed|success(?:es)?)\b", low)
    ]
    if structured:
        if any(value > 0 for value in negative_counts):
            return "fail"
        if negative_counts and all(value == 0 for value in negative_counts) and any(
            value > 0 for value in positive_counts
        ):
            return "pass"

    explicit_fail = bool(
        re.search(
            r"\bfailed\s*\(|\bfailures?\s*[:=]\s*[1-9]\d*|"
            r"\b(?:test|tests)\s+(?:has\s+|have\s+)?failed\b|"
            r"(?:✗|❌)[^\n]*(?:fail|error|incorrect|missing)",
            low,
        )
    )
    explicit_pass = bool(
        re.search(
            r"(?:✓|✅)[^\n]*(?:pass|success|correct|fixed|works)|"
            r"\b(?:all|both)\s+(?:selected\s+)?tests?\s+(?:now\s+)?pass(?:ed)?\b|"
            r"\btests?\s+passed\b|(?:^|\n)\s*ok\s*(?:\n|$)",
            low,
        )
    )
    if explicit_fail and not explicit_pass:
        return "fail"
    fatal_runtime_error = any(
        x in low
        for x in [
            "traceback (most recent call last)",
            "assertionerror",
            "modulenotfounderror",
        ]
    )
    if fatal_runtime_error and not explicit_pass:
        return "fail"

    exit_codes = re.findall(r"exit code\s+(-?\d+)", low)
    exit_code = int(exit_codes[-1]) if exit_codes else None
    if exit_code is not None and exit_code != 0:
        return "fail"

    test_command = bool(
        re.search(
            r"\b(pytest|py\.test|unittest|tox|nosetests|runtests(?:\.py)?)\b",
            command_low or low,
        )
    )
    if exit_code == 0 and test_command:
        return "pass"

    if explicit_pass and not explicit_fail:
        return "pass"

    # A zero exit code from an arbitrary diagnostic script only establishes
    # that the script ran.  It does not establish that the repair passed.
    if exit_code == 0:
        return "unknown"

    if explicit_fail or explicit_pass:
        return "unknown"

    if structured and any(value > 0 for value in positive_counts):
        return "pass"
    if re.search(r"(?:^|\n)\s*ok\s*(?:\n|$)", low):
        return "pass"

    neutralized = re.sub(
        r"\b(?:0|no)\s+(?:failed|failures?|errors?)\b",
        "",
        low,
    )
    if any(x in neutralized for x in ["failed", "failure", " error", "error:"]):
        return "fail"
    return "unknown"


def infer_path_from_text(text):
    if not text:
        return ""
    for pat in [r"'path'\s*:\s*'([^']+)'", r'"path"\s*:\s*"([^"]+)"']:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def is_temp_or_test_path(path):
    p = (path or "").replace("\\", "/").lower()
    if not p:
        return False
    base = p.rsplit("/", 1)[-1]
    if p.startswith("/tmp/") or "/tmp/" in p or p.startswith("tmp/"):
        return True
    if p.startswith("tests/") or "/tests/" in p or base.startswith("test_") or base.endswith("_test.py"):
        return True
    temp_words = ["repro", "reproduce", "debug", "temp", "tmp", "script"]
    return any(w in base for w in temp_words)


def is_patch_edit(action, path):
    if action not in EDIT_ACTIONS:
        return False
    if is_temp_or_test_path(path):
        return False
    if not path:
        return action in {"Modify", "Delete"}
    return True


def add_event(events, action, cue, text="", outcome="", path="", executes=False):
    if action not in ACTIONS:
        action = "Execute"
    path = path or infer_path_from_text(text)
    events.append(
        {
            "action": action,
            "cue": cue,
            "text": text or "",
            "outcome": outcome or "",
            "path": path,
            "is_temp_or_test": is_temp_or_test_path(path),
            "is_patch_edit": is_patch_edit(action, path),
            "executes": bool(executes),
        }
    )


def extract_lingxi(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    events = []
    tool_counter = Counter()
    tags = Counter(re.findall(r"<([^/\s>]+)", text))

    # Lingxi exposes long explicit reasoning sections. Count each major reasoning block once.
    for tag in [
        "problem_decoder",
        "issue_analysis",
        "current_behavior",
        "expected_behavior",
        "root_cause",
        "solution_mapper",
        "code_change_plan",
    ]:
        for _ in re.finditer(rf"<{tag}(?:\s+\d+)?>", text):
            add_event(events, "Understand", tag)
            tool_counter[tag] += 1

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "### 🎯 Action" in line or line.strip() in {"### Action", "Action:"}:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                action, cue = classify_lingxi_action(lines[j])
                add_event(events, action, cue, lines[j])
                tool_counter[cue] += 1
    return events, tool_counter, {"tags": tags, "chars": len(text)}


def moatless_final_path(nodes):
    by_id = {n.get("node_id"): n for n in nodes if isinstance(n, dict)}
    terminal = [n for n in nodes if isinstance(n, dict) and n.get("terminal")]
    if terminal:
        leaf = terminal[-1]
    else:
        leaf = max(
            [n for n in nodes if isinstance(n, dict)],
            key=lambda n: (len(str(n.get("output", ""))) > 0, n.get("node_id", -1)),
        )
    path = []
    cur = leaf
    seen = set()
    while isinstance(cur, dict) and cur.get("node_id") not in seen:
        path.append(cur)
        seen.add(cur.get("node_id"))
        cur = by_id.get(cur.get("parent_id"))
    return list(reversed(path))


def extract_moatless(path: Path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    nodes = obj.get("nodes", [])
    linear = moatless_final_path(nodes)
    events = []
    tool_counter = Counter()
    branch_nodes = len(nodes) - len(linear)

    for node in linear:
        for field in ["assistant_message"]:
            val = node.get(field)
            if isinstance(val, str) and val.strip():
                add_event(events, "Understand", field, val)
                tool_counter[field] += 1
        if node.get("thinking_blocks"):
            add_event(events, "Understand", "thinking_blocks", str(node.get("thinking_blocks")))
            tool_counter["thinking_blocks"] += 1
        elif node.get("thoughts"):
            add_event(events, "Understand", "thoughts", str(node.get("thoughts")))
            tool_counter["thoughts"] += 1
        for step in node.get("action_steps") or []:
            action_obj = step.get("action") if isinstance(step, dict) else {}
            obs = step.get("observation") if isinstance(step, dict) else {}
            obs_text = str(obs)
            action, cue = classify_moatless_action(action_obj, obs_text)
            outcome = execute_outcome(obs_text) if action == "Execute" else ""
            path = ""
            executes = False
            if isinstance(action_obj, dict):
                path = str(action_obj.get("path") or action_obj.get("file_path") or "")
                executes = bool(action_obj.get("execute"))
            add_event(events, action, cue, obs_text, outcome, path=path, executes=executes)
            tool_counter[cue] += 1
    return events, tool_counter, {"nodes": len(nodes), "linear_nodes": len(linear), "branch_nodes": branch_nodes}


def extract_openhands(path: Path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    events = []
    tool_counter = Counter()
    pending = {}

    for msg in obj:
        role = msg.get("role")
        if role == "assistant":
            content_text = text_from_content(msg.get("content"))
            if content_text.strip():
                add_event(events, "Understand", "assistant_text", content_text)
                tool_counter["assistant_text"] += 1
            for call in msg.get("tool_calls") or []:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                name = fn.get("name")
                args = parse_json_args(fn.get("arguments", ""))
                action, cue = classify_openhands_tool(name, args)
                path = str(args.get("path") or "")
                add_event(events, action, cue, str(args), path=path)
                event = events[-1]
                tool_counter[cue] += 1
                if call.get("id"):
                    pending[call["id"]] = event
        elif role == "tool":
            content_text = text_from_content(msg.get("content"))
            event = pending.get(msg.get("tool_call_id"))
            if event and event["action"] == "Execute":
                event["outcome"] = execute_outcome(content_text)
                event["text"] = (event.get("text", "") + "\n" + content_text)[-5000:]
    return events, tool_counter, {"messages": len(obj)}


def compress(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return out


def trajectory_features(events):
    actions = [e["action"] for e in events]
    first_patch_edit = next((i for i, e in enumerate(events) if e.get("is_patch_edit")), None)
    has = {a: any(x == a for x in actions) for a in ACTIONS}
    pre_events = events[:first_patch_edit] if first_patch_edit is not None else events
    post_events = events[first_patch_edit + 1 :] if first_patch_edit is not None else []
    pre = [e["action"] for e in pre_events]
    post = [e["action"] for e in post_events]

    edit_indices = [i for i, a in enumerate(actions) if a in EDIT_ACTIONS]
    patch_edit_indices = [i for i, e in enumerate(events) if e.get("is_patch_edit")]
    execute_indices = [i for i, a in enumerate(actions) if a == "Execute"]
    exec_like_indices = [i for i, e in enumerate(events) if e["action"] == "Execute" or e.get("executes")]
    post_patch_exec = [i for i in exec_like_indices if first_patch_edit is not None and i > first_patch_edit]
    pre_patch_exec = [i for i in exec_like_indices if first_patch_edit is None or i < first_patch_edit]
    pre_patch_temp_create = [
        i
        for i, e in enumerate(pre_events)
        if e["action"] in {"Create", "Modify"} and e.get("is_temp_or_test")
    ]

    validation_refinement_loops = 0
    for ei in post_patch_exec:
        if any(j > ei for j in patch_edit_indices):
            validation_refinement_loops += 1

    execute_fails = sum(1 for e in events if e["action"] == "Execute" and e.get("outcome") == "fail")
    execute_passes = sum(1 for e in events if e["action"] == "Execute" and e.get("outcome") == "pass")

    return {
        "n_events": len(actions),
        "distinct_actions": len(set(actions)),
        "compressed_len": len(compress(actions)),
        "has_problem_understanding_evidence": has["Understand"],
        "has_failure_reproduction_evidence": bool(pre_patch_exec or pre_patch_temp_create),
        "has_fault_localization_evidence": any(a in {"Search", "Read"} for a in pre),
        "has_patch_construction_evidence": first_patch_edit is not None,
        "has_patch_validation_evidence": bool(post_patch_exec),
        "has_patch_refinement_evidence": validation_refinement_loops > 0,
        "validation_refinement_loops": validation_refinement_loops,
        "pre_edit_exec_count": len(pre_patch_exec),
        "post_edit_exec_count": len(post_patch_exec),
        "edit_count": len(edit_indices),
        "patch_edit_count": len(patch_edit_indices),
        "temp_or_test_edit_count": sum(1 for e in events if e["action"] in EDIT_ACTIONS and e.get("is_temp_or_test")),
        "execute_count": len(execute_indices),
        "execute_fail_count": execute_fails,
        "execute_pass_count": execute_passes,
        **{f"has_{a.lower()}": has[a] for a in ACTIONS},
        **{f"count_{a.lower()}": actions.count(a) for a in ACTIONS},
    }


def rate(rows, key, agent=None, value=True):
    subset = [r for r in rows if (agent is None or r["agent"] == agent) and bool(r.get(key)) == value]
    if not subset:
        return None
    resolved = sum(1 for r in subset if r["resolved"])
    return len(subset), resolved, resolved / len(subset)


def pct(n, d):
    return 0 if d == 0 else 100 * n / d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out-dir", default="data/processed/profile")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out = root / args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    outcomes = load_outcomes(root)
    rows = []
    action_totals = defaultdict(Counter)
    tool_totals = defaultdict(Counter)
    meta_rows = []

    extractors = {
        "lingxi": (root / "data/raw/lingxi", "*.traj", extract_lingxi),
        "moatless": (root / "data/raw/moatless", "*.json", extract_moatless),
        "openhands": (root / "data/raw/openhands", "*.json", extract_openhands),
    }

    for agent, (directory, pattern, extractor) in extractors.items():
        for path in sorted(directory.glob(pattern)):
            instance_id = path.stem
            events, tools, meta = extractor(path)
            feats = trajectory_features(events)
            row = {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": instance_id in outcomes[agent],
                **feats,
            }
            rows.append(row)
            action_totals[agent].update(e["action"] for e in events)
            tool_totals[agent].update(tools)
            meta_rows.append({"agent": agent, "instance_id": instance_id, **meta})

    fieldnames = list(rows[0].keys())
    with (out / "trajectory_profile.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with (out / "format_meta.csv").open("w", newline="", encoding="utf-8") as f:
        keys = sorted({k for r in meta_rows for k in r})
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(meta_rows)

    report = []
    report.append("# Taxonomy Coverage Profile\n")
    report.append(f"Total trajectories: {len(rows)}\n")

    report.append("## Action Event Totals\n")
    report.append("| Agent | " + " | ".join(ACTIONS) + " | Total |")
    report.append("| --- | " + " | ".join(["---:"] * (len(ACTIONS) + 1)) + " |")
    for agent in ["lingxi", "moatless", "openhands"]:
        total = sum(action_totals[agent].values())
        vals = [str(action_totals[agent][a]) for a in ACTIONS]
        report.append(f"| {agent} | " + " | ".join(vals) + f" | {total} |")

    report.append("\n## Trajectory-Level Action Coverage\n")
    report.append("| Agent | " + " | ".join(ACTIONS) + " |")
    report.append("| --- | " + " | ".join(["---:"] * len(ACTIONS)) + " |")
    for agent in ["lingxi", "moatless", "openhands"]:
        subset = [r for r in rows if r["agent"] == agent]
        vals = []
        for a in ACTIONS:
            n = sum(1 for r in subset if r[f"has_{a.lower()}"])
            vals.append(f"{n}/500 ({pct(n,500):.1f}%)")
        report.append(f"| {agent} | " + " | ".join(vals) + " |")

    subtask_keys = [
        ("Problem Understanding", "has_problem_understanding_evidence"),
        ("Failure Reproduction", "has_failure_reproduction_evidence"),
        ("Fault Localization", "has_fault_localization_evidence"),
        ("Patch Construction", "has_patch_construction_evidence"),
        ("Patch Refinement", "has_patch_refinement_evidence"),
        ("Patch Validation", "has_patch_validation_evidence"),
    ]
    report.append("\n## Candidate Subtask Evidence Coverage\n")
    report.append("| Agent | " + " | ".join(k for k, _ in subtask_keys) + " |")
    report.append("| --- | " + " | ".join(["---:"] * len(subtask_keys)) + " |")
    for agent in ["lingxi", "moatless", "openhands"]:
        subset = [r for r in rows if r["agent"] == agent]
        vals = []
        for _, key in subtask_keys:
            n = sum(1 for r in subset if r[key])
            vals.append(f"{n}/500 ({pct(n,500):.1f}%)")
        report.append(f"| {agent} | " + " | ".join(vals) + " |")

    report.append("\n## Feature vs Resolved Rate\n")
    report.append("| Feature | Agent | n | resolved | resolved rate |")
    report.append("| --- | --- | ---: | ---: | ---: |")
    features = [k for _, k in subtask_keys] + [
        "has_understand",
        "has_execute",
        "has_create",
        "has_modify",
        "has_delete",
    ]
    for feature in features:
        for agent in ["all", "lingxi", "moatless", "openhands"]:
            res = rate(rows, feature, None if agent == "all" else agent, True)
            if res:
                n, resolved, rr = res
                report.append(f"| {feature} | {agent} | {n} | {resolved} | {rr:.3f} |")

    report.append("\n## Loop Distribution\n")
    report.append("| Agent | no loop | 1 loop | 2+ loops | mean loops |")
    report.append("| --- | ---: | ---: | ---: | ---: |")
    for agent in ["lingxi", "moatless", "openhands"]:
        subset = [r for r in rows if r["agent"] == agent]
        no = sum(1 for r in subset if r["validation_refinement_loops"] == 0)
        one = sum(1 for r in subset if r["validation_refinement_loops"] == 1)
        two = sum(1 for r in subset if r["validation_refinement_loops"] >= 2)
        mean = sum(r["validation_refinement_loops"] for r in subset) / len(subset)
        report.append(f"| {agent} | {no} | {one} | {two} | {mean:.2f} |")

    report.append("\n## Top Tool Cues\n")
    for agent in ["lingxi", "moatless", "openhands"]:
        report.append(f"\n### {agent}\n")
        report.append("| Cue | n |")
        report.append("| --- | ---: |")
        for cue, n in tool_totals[agent].most_common(25):
            report.append(f"| `{cue}` | {n} |")

    (out / "coverage_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(out / "coverage_report.md")
    print(out / "trajectory_profile.csv")


if __name__ == "__main__":
    main()
