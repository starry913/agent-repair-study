#!/usr/bin/env python3
import ast
import csv
import difflib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import profile_taxonomy_coverage as prof


ACTIONS = ["Reason", "Read", "Search", "Run", "Add", "Revise", "Remove", "Setup"]
EDIT_ACTIONS = {"Add", "Revise", "Remove"}
SUBTASKS = [
    "Problem Understanding",
    "Failure Reproduction",
    "Fault Localization",
    "Patch Construction",
    "Patch Refinement",
    "Patch Validation",
]
SUBTASK_CODES = {
    "Problem Understanding": "PU",
    "Failure Reproduction": "FR",
    "Fault Localization": "FL",
    "Patch Construction": "PC",
    "Patch Refinement": "PR",
    "Patch Validation": "PV",
}

SOURCE_SUFFIXES = (
    ".py",
    ".pyi",
    ".rst",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".c",
    ".h",
    ".cpp",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
)

DIAGNOSTIC_WORDS = (
    "repro",
    "reproduce",
    "debug",
    "verify",
    "verification",
    "validate",
    "validation",
    "demo",
    "demonstrate",
    "investigate",
    "experiment",
    "edge_case",
    "scratch",
    "temporary",
    "tmp",
    "script",
)

DIAGNOSTIC_DIRECTORIES = {
    "test",
    "tests",
    "testing",
    "fixtures",
    "examples",
    "example",
    "scripts",
    "benchmarks",
    "benchmark",
    "tools",
}

REASON_CUES = {
    "problem_decoder",
    "issue_analysis",
    "current_behavior",
    "expected_behavior",
    "root_cause",
    "solution_mapper",
    "code_change_plan",
    "problem_solver",
    "think",
    "thinking_blocks",
    "thoughts",
    "assistant_text",
    "assistant_message",
}

REASON_PATTERNS = [
    r"\b(root cause|caused by|because|therefore|this means|indicates|suggests)\b",
    r"\b(issue|problem|bug|failure|failing|error|traceback|assertion|regression)\b",
    r"\b(expected|actual|current behavior|observed behavior)\b",
    r"\b(hypothesis|likely|probably|seems|appears|diagnos|analysis|reason)\b",
    r"\b(fix|patch|solution|approach|need to|should|must|modify|change|implement)\b",
    r"\b(target|relevant|related|call chain|method|function|class|logic)\b",
]

WEAK_REASON_PATTERNS = [
    r"^\s*(let me|i(?:'ll| will)|now let me|next,? i|great!?|perfect!?|ok(?:ay)?)[\s,.:!-]",
    r"^\s*(we need|i need) to (look|check|inspect|open|read|run|search|find)\b",
    r"^\s*(done|finished|completed|all tests pass|the fix is complete)\b",
    r"^\s*(now|next|then),?\s+(i(?:'ll| will)|we(?:'ll| will))\s+(look|check|inspect|open|read|run|search|find|edit)\b",
    r"^\s*(let's|lets)\s+(look|check|inspect|open|read|run|search|find|edit)\b",
]

BLOCKED_PATTERNS = [
    r"no module named",
    r"modulenotfounderror",
    r"importerror",
    r"permission denied",
    r"command not found",
    r"no such file or directory",
    r"not installed",
    r"could not install",
    r"dependency",
    r"environment",
    r"timeout",
]


def norm_path(path):
    if not path:
        return ""
    p = str(path).replace("\\", "/")
    p = re.sub(r"^/workspace/[^/]+/", "", p)
    p = re.sub(r"^/testbed/", "", p)
    p = re.sub(r"^\./", "", p)
    return p


def is_test_path(path):
    p = norm_path(path).lower()
    if not p:
        return False
    parts = [part for part in p.split("/") if part]
    base = parts[-1] if parts else ""
    stem = base.rsplit(".", 1)[0]
    return (
        any(part in {"test", "tests", "testing", "fixtures"} for part in parts[:-1])
        or stem.startswith("test_")
        or stem.endswith("_test")
    )


def is_temp_or_test(path):
    normalized = norm_path(path)
    return prof.is_temp_or_test_path(normalized) or is_diagnostic_path(normalized)


def is_source_like(path, ref=None):
    p = norm_path(path).lower()
    if not p:
        return False
    base = p.rsplit("/", 1)[-1]
    if "." not in base or not base.endswith(SOURCE_SUFFIXES):
        return False
    reference_files = {norm_path(x).lower() for x in (ref or {}).get("patch_files", set())}
    if p in reference_files and not is_test_path(p):
        return True
    return not prof.is_temp_or_test_path(p) and not is_diagnostic_path(p)


def is_diagnostic_path(path):
    p = norm_path(path).lower()
    if not p:
        return False
    parts = [part for part in p.split("/") if part]
    if not parts:
        return False
    base = parts[-1]
    stem = base.rsplit(".", 1)[0]
    if any(part in DIAGNOSTIC_DIRECTORIES for part in parts[:-1]):
        return True
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    stem_tokens = set(token for token in re.split(r"[_\-.]+", stem) if token)
    return any(
        word in stem_tokens
        or stem == word
        or re.search(rf"(?:^|[_\-.]){re.escape(word)}(?:$|[_\-.])", stem)
        for word in DIAGNOSTIC_WORDS
    )


def infer_command_path(command):
    command = str(command or "")
    patterns = [
        r"\b(?:touch|tee)\s+(?:-a\s+)?['\"]?([^\s'\";|]+)",
        r"\b(?:rm|unlink)\s+(?:-[rf]+\s+)?['\"]?([^\s'\";|]+)",
        r"(?:>>|>)\s*['\"]?([^\s'\";|]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            return norm_path(match.group(1))
    return ""


def execute_outcome(text, command="", structured=False):
    return prof.execute_outcome(text, command, structured)


def text_from_content(content):
    return prof.text_from_content(content)


def parse_json_args(s):
    return prof.parse_json_args(s)


def infer_path(text):
    if not text:
        return ""
    for pat in [
        r"'(?:path|file_path|file_name)'\s*:\s*'([^']+)'",
        r'"(?:path|file_path|file_name)"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, text)
        if m:
            return norm_path(m.group(1))
    return ""


def strict_reason(cue, text):
    cue = str(cue or "")
    text = str(text or "")
    low = text.lower()
    stripped = text.strip()
    if cue.lower() in {"verifiedfinishargs", "finish", "finishargs"}:
        return False
    if cue in {
        "problem_decoder",
        "issue_analysis",
        "current_behavior",
        "expected_behavior",
        "root_cause",
        "solution_mapper",
        "code_change_plan",
        "problem_solver",
    }:
        return True
    if cue not in REASON_CUES and len(stripped) < 120:
        return False
    if any(re.search(p, low) for p in WEAK_REASON_PATTERNS) and len(stripped) < 260:
        return False
    hits = sum(1 for p in REASON_PATTERNS if re.search(p, low))
    if cue in {"think", "thinking_blocks", "thoughts"}:
        return hits >= 2 and len(stripped) >= 120
    if cue in {"assistant_text", "assistant_message"}:
        return hits >= 2 and len(stripped) >= 180
    return hits >= 2 and len(stripped) >= 140


def add_event(
    events,
    action,
    cue,
    text="",
    path="",
    outcome="",
    executes=False,
    old_str="",
    new_str="",
    command="",
):
    if action not in ACTIONS:
        action = "Run"
    if action == "Reason" and not strict_reason(cue, text):
        return
    path = norm_path(path or infer_path(text) or infer_command_path(command))
    events.append(
        {
            "event_index": len(events),
            "action": action,
            "cue": cue,
            "text": text or "",
            "path": path,
            "outcome": outcome or "",
            "executes": bool(executes),
            "old_str": old_str or "",
            "new_str": new_str or "",
            "command": command or "",
            "is_temp_or_test": is_temp_or_test(path),
            "is_source_path": is_source_like(path),
            "blocked": any(re.search(p, (text or "").lower()) for p in BLOCKED_PATTERNS),
            "is_file_creation": False,
            "created_by_agent": False,
            "is_diagnostic_path": False,
            "is_diagnostic_artifact": False,
            "is_product_source_edit": False,
        }
    )


def edit_action_from_old_new(old_str, new_str, default="Revise"):
    old = "" if old_str is None else str(old_str)
    new = "" if new_str is None else str(new_str)
    if old.strip() and not new.strip():
        return "Remove"
    if new.strip() and not old.strip():
        return "Add"
    return default


def classify_command(command):
    c = (command or "").lower().strip()
    if not c:
        return "Run"
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
    if re.search(r"\brm\s+|\bunlink\b|\bdelete\b", c):
        return "Remove"
    if re.search(r"\bsed\s+-i\b|\bapply_patch\b|\bpatch\s+|\bperl\s+-pi\b|\bstr_replace\b", c):
        return "Revise"
    if re.search(r"\btouch\b|\bcat\s*>|\btee\s+|\bprintf\s+.*>", c):
        return "Add"
    if re.search(r"\b(rg|grep|find|git\s+grep)\b", c):
        return "Search"
    if re.search(r"\b(cat|sed\s+-n|head|tail|ls|tree|pwd)\b", c):
        return "Read"
    return "Run"


def extract_lingxi(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    events = []
    for tag in [
        "problem_decoder",
        "issue_analysis",
        "current_behavior",
        "expected_behavior",
        "root_cause",
        "solution_mapper",
        "code_change_plan",
    ]:
        for m in re.finditer(rf"<{tag}(?:\s+\d+)?>", text):
            add_event(events, "Reason", tag, text[m.start() : m.start() + 1200])

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "### 🎯 Action" not in line and line.strip() not in {"### Action", "Action:"}:
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            continue
        s = lines[j].strip()
        low = s.lower()
        name = re.split(r"[\(\{]", s, 1)[0].strip()
        if name == "think" or low.startswith("think("):
            add_event(events, "Reason", "think", s)
        elif name == "ask_repository_agent" or "ask_repository_agent" in low:
            add_event(events, "Search", name or "ask_repository_agent", s)
        elif name == "str_replace_based_edit_tool" or "str_replace_based_edit_tool" in low:
            args = {}
            m = re.search(r"str_replace_based_edit_tool\((.*)\)\s*$", s)
            if m:
                try:
                    val = ast.literal_eval(m.group(1))
                    args = val if isinstance(val, dict) else {}
                except Exception:
                    args = {}
            cmd = str(args.get("command", "")).lower()
            path_arg = args.get("path", "")
            old_str = str(args.get("old_str") or "")
            new_str = str(args.get("new_str") or "")
            if cmd == "view":
                add_event(events, "Read", "str_replace_based_edit_tool.view", s, path_arg)
            elif cmd in {"create", "insert"}:
                add_event(events, "Add", f"str_replace_based_edit_tool.{cmd}", s, path_arg, old_str=old_str, new_str=new_str)
            elif cmd == "str_replace":
                act = edit_action_from_old_new(old_str, new_str)
                add_event(events, act, "str_replace_based_edit_tool.str_replace", s, path_arg, old_str=old_str, new_str=new_str)
            elif cmd == "undo_edit":
                add_event(events, "Revise", "str_replace_based_edit_tool.undo_edit", s, path_arg)
            else:
                add_event(events, "Revise", f"str_replace_based_edit_tool.{cmd or 'unknown'}", s, path_arg)
        elif name == "bash" or low.startswith("bash("):
            command = ""
            m = re.search(r"bash\((.*)\)\s*$", s)
            if m:
                try:
                    val = ast.literal_eval(m.group(1))
                    command = str(val.get("command", "")) if isinstance(val, dict) else ""
                except Exception:
                    command = ""
            act = classify_command(command)
            add_event(
                events,
                act,
                "bash",
                s,
                # Lingxi's public format omits command stdout/stderr.  The next
                # reasoning turn may summarize it, but that is not tool output.
                outcome="",
                executes=act == "Run",
                command=command,
            )
        elif "search" in low or "grep" in low or "find" in low:
            add_event(events, "Search", name or "unknown", s)
        elif any(x in low for x in ["view", "read", "open", "list", "show_file", "cat"]):
            add_event(events, "Read", name or "unknown", s)
        elif any(x in low for x in ["create", "write_new", "new_file", "insert", "append"]):
            add_event(events, "Add", name or "unknown", s)
        elif any(x in low for x in ["delete", "remove"]):
            add_event(events, "Remove", name or "unknown", s)
        elif any(x in low for x in ["edit", "modify", "replace", "patch"]):
            add_event(events, "Revise", name or "unknown", s)
        elif any(x in low for x in ["install", "setup", "mkdir", "chmod", "configure"]):
            add_event(events, "Setup", name or "unknown", s)
        elif any(x in low for x in ["run", "execute", "pytest", "test", "python", "bash"]):
            add_event(events, "Run", name or "unknown", s, outcome="", executes=True)
        else:
            add_event(events, "Run", name or "unknown", s, outcome="", executes=True)
    return events


def moatless_final_path(nodes):
    return prof.moatless_final_path(nodes)


def moatless_action_class(action):
    return prof.moatless_action_class(action)


def extract_moatless(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    events = []
    for node in moatless_final_path(obj.get("nodes", [])):
        val = node.get("assistant_message")
        if isinstance(val, str) and val.strip():
            add_event(events, "Reason", "assistant_message", val)
        if node.get("thinking_blocks"):
            add_event(events, "Reason", "thinking_blocks", str(node.get("thinking_blocks")))
        elif node.get("thoughts"):
            add_event(events, "Reason", "thoughts", str(node.get("thoughts")))
        for step in node.get("action_steps") or []:
            action_obj = step.get("action") if isinstance(step, dict) else {}
            obs = step.get("observation") if isinstance(step, dict) else {}
            obs_text = str(obs)
            name = moatless_action_class(action_obj)
            low = name.lower()
            path_arg = ""
            old_str = ""
            new_str = ""
            executes = False
            if isinstance(action_obj, dict):
                path_arg = action_obj.get("path") or action_obj.get("file_path") or ""
                old_str = str(action_obj.get("old_str") or "")
                new_str = str(action_obj.get("new_str") or "")
                executes = bool(action_obj.get("execute"))
            if "cleanupcontext" in low:
                add_event(events, "Setup", name, obs_text, path_arg)
            elif any(x in low for x in ["semanticsearch", "greptool", "glob", "find", "search"]):
                add_event(events, "Search", name, obs_text, path_arg)
            elif any(x in low for x in ["readfile", "listfiles", "view", "show"]):
                add_event(events, "Read", name, obs_text, path_arg)
            elif "create" in low or "append" in low or "insert" in low:
                add_event(events, "Add", name, obs_text, path_arg, old_str=old_str, new_str=new_str)
            elif "stringreplace" in low or "replace" in low or "edit" in low or "patch" in low:
                act = edit_action_from_old_new(old_str, new_str)
                add_event(events, act, name, obs_text, path_arg, old_str=old_str, new_str=new_str)
            elif any(x in low for x in ["delete", "remove"]):
                add_event(events, "Remove", name, obs_text, path_arg)
            elif any(x in low for x in ["runtests", "run", "execute", "python"]):
                add_event(
                    events,
                    "Run",
                    name,
                    obs_text,
                    path_arg,
                    execute_outcome(obs_text, structured="runtests" in low),
                    executes=True,
                )
            elif "finish" in low:
                add_event(events, "Reason", name, obs_text)
            elif any(x in low for x in ["setup", "install"]):
                add_event(events, "Setup", name, obs_text)
            else:
                act = classify_command(obs_text)
                add_event(
                    events,
                    act,
                    name,
                    obs_text,
                    path_arg,
                    execute_outcome(obs_text) if act == "Run" else "",
                    executes=act == "Run" or executes,
                )
    return events


def extract_openhands(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    events = []
    pending = {}
    for msg in obj:
        role = msg.get("role")
        if role == "assistant":
            content = text_from_content(msg.get("content"))
            if content.strip():
                add_event(events, "Reason", "assistant_text", content)
            for call in msg.get("tool_calls") or []:
                fn = call.get("function", {}) if isinstance(call, dict) else {}
                name = (fn.get("name") or "unknown").lower()
                args = parse_json_args(fn.get("arguments", ""))
                path_arg = args.get("path") or ""
                old_str = str(args.get("old_str") or "")
                new_str = str(args.get("new_str") or "")
                if name == "think":
                    add_event(events, "Reason", "think", str(args))
                elif name in {"execute_bash", "bash"}:
                    command = args.get("command", "")
                    act = classify_command(command)
                    add_event(
                        events,
                        act,
                        name,
                        str(args),
                        outcome="" if act != "Run" else execute_outcome(str(args), command),
                        executes=act == "Run",
                        command=command,
                    )
                elif name in {"str_replace_editor", "file_editor"}:
                    cmd = str(args.get("command", "")).lower()
                    if cmd == "view":
                        add_event(events, "Read", f"{name}.view", str(args), path_arg)
                    elif cmd in {"create", "insert"}:
                        add_event(events, "Add", f"{name}.{cmd}", str(args), path_arg, old_str=old_str, new_str=new_str)
                    elif cmd == "str_replace":
                        act = edit_action_from_old_new(old_str, new_str)
                        add_event(events, act, f"{name}.str_replace", str(args), path_arg, old_str=old_str, new_str=new_str)
                    elif cmd == "undo_edit":
                        add_event(events, "Revise", f"{name}.undo_edit", str(args), path_arg)
                    else:
                        add_event(events, "Revise", f"{name}.{cmd or 'unknown'}", str(args), path_arg)
                elif "search" in name:
                    add_event(events, "Search", name, str(args), path_arg)
                elif "read" in name or "view" in name:
                    add_event(events, "Read", name, str(args), path_arg)
                elif "create" in name or "insert" in name or "append" in name:
                    add_event(events, "Add", name, str(args), path_arg)
                elif "delete" in name or "remove" in name:
                    add_event(events, "Remove", name, str(args), path_arg)
                elif "edit" in name or "replace" in name or "patch" in name:
                    add_event(events, "Revise", name, str(args), path_arg)
                else:
                    add_event(events, "Run", name, str(args), path_arg, executes=True)
                if call.get("id") and events:
                    pending[call["id"]] = events[-1]
        elif role == "tool":
            content = text_from_content(msg.get("content"))
            event = pending.get(msg.get("tool_call_id"))
            if event and event["action"] == "Run":
                event["outcome"] = execute_outcome(content, event.get("command", ""))
                event["text"] = (event.get("text", "") + "\n" + content)[-5000:]
    return events


def parse_patch_files_and_lines(patch):
    files = set()
    added = defaultdict(set)
    removed = defaultdict(set)
    cur = ""
    for line in (patch or "").splitlines():
        if line.startswith("diff --git "):
            m = re.search(r" b/(\S+)", line)
            cur = norm_path(m.group(1)) if m else ""
            if cur:
                files.add(cur)
        elif line.startswith("+++ b/"):
            cur = norm_path(line[6:].strip())
            if cur:
                files.add(cur)
        elif cur and line.startswith("+") and not line.startswith("+++"):
            v = line[1:].strip()
            if v:
                added[cur].add(v)
        elif cur and line.startswith("-") and not line.startswith("---"):
            v = line[1:].strip()
            if v:
                removed[cur].add(v)
    return files, added, removed


def parse_json_list(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def load_reference(root, out_dir):
    candidates = sorted(
        Path.home().glob(".cache/huggingface/hub/datasets--princeton-nlp--SWE-bench_Verified/blobs/*"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    explicit = os.environ.get("SWE_BENCH_VERIFIED_PARQUET")
    parquet = Path(explicit).expanduser() if explicit else next((p for p in candidates if p.stat().st_size > 100000), None)
    if not parquet:
        raise FileNotFoundError("Set SWE_BENCH_VERIFIED_PARQUET to the reference Parquet file, or populate the SWE-bench Verified Hugging Face cache")
    con = duckdb.connect()
    rows = con.execute("select * from read_parquet(?)", [str(parquet)]).fetchall()
    cols = [d[0] for d in con.description]
    refs = {}
    meta_rows = []
    for raw in rows:
        obj = dict(zip(cols, raw))
        inst = obj["instance_id"]
        patch_files, added, removed = parse_patch_files_and_lines(obj.get("patch", ""))
        test_files, test_added, test_removed = parse_patch_files_and_lines(obj.get("test_patch", ""))
        fail_tests = parse_json_list(obj.get("FAIL_TO_PASS", "[]"))
        refs[inst] = {
            "repo": obj.get("repo", ""),
            "patch_files": patch_files,
            "test_files": test_files,
            "fail_tests": fail_tests,
            "added": added,
            "removed": removed,
            "test_added": test_added,
            "test_removed": test_removed,
            "problem_statement": obj.get("problem_statement", ""),
        }
        meta_rows.append(
            {
                "instance_id": inst,
                "repo": obj.get("repo", ""),
                "patch_files": ";".join(sorted(patch_files)),
                "test_files": ";".join(sorted(test_files)),
                "fail_to_pass": ";".join(fail_tests),
            }
        )
    write_csv(out_dir / "pre12_reference_patch_meta.csv", meta_rows)
    return refs


def is_explicit_file_creation(e):
    cue = str(e.get("cue", "")).lower()
    command = str(e.get("command", "")).lower()
    if any(
        marker in cue
        for marker in (
            ".create",
            "createpythonfileargs",
            "createfile",
            "new_file",
        )
    ):
        return True
    if e.get("action") == "Add" and re.search(
        r"\b(?:touch|tee)\b|(?:^|\s)(?:>>|>)\s*", command
    ):
        return True
    return False


def is_nested_product_source(path):
    p = norm_path(path).lower()
    parts = [part for part in p.split("/") if part]
    if len(parts) < 2 or not is_source_like(p):
        return False
    if any(part in DIAGNOSTIC_DIRECTORIES for part in parts[:-1]):
        return False
    return not is_diagnostic_path(p)


def annotate_event_provenance(events, ref):
    created_paths = set()
    patch_files = {norm_path(p) for p in ref.get("patch_files", set())}
    for event in events:
        path = norm_path(event.get("path", ""))
        if path:
            event["path"] = path
        explicit_creation = is_explicit_file_creation(event)
        if explicit_creation and path:
            created_paths.add(path)
        created_by_agent = bool(path and path in created_paths)
        intrinsic_diagnostic = is_diagnostic_path(path)
        reference_source_target = path in patch_files and not is_test_path(path)
        root_created = (
            created_by_agent
            and len([x for x in path.split("/") if x]) == 1
            and not reference_source_target
        )
        diagnostic_path = intrinsic_diagnostic or root_created
        if reference_source_target:
            diagnostic_path = False
        if created_by_agent and path not in patch_files and not is_nested_product_source(path):
            diagnostic_path = True
        diagnostic = diagnostic_path and event.get("action") in EDIT_ACTIONS
        product_edit = (
            event.get("action") in EDIT_ACTIONS
            and bool(path)
            and is_source_like(path, ref)
            and not diagnostic_path
            and (path in patch_files or not created_by_agent or is_nested_product_source(path))
        )
        event["is_file_creation"] = bool(explicit_creation)
        event["created_by_agent"] = created_by_agent
        event["is_diagnostic_path"] = diagnostic_path
        event["is_diagnostic_artifact"] = diagnostic
        event["is_product_source_edit"] = product_edit
        event["is_temp_or_test"] = is_temp_or_test(path)
        event["is_source_path"] = is_source_like(path, ref)


def is_patch_edit(e, ref=None):
    if ref is None and "is_product_source_edit" in e:
        return bool(e.get("is_product_source_edit"))
    if e.get("action") not in EDIT_ACTIONS:
        return False
    path = norm_path(e.get("path", ""))
    if not path or not is_source_like(path, ref):
        return False
    if e.get("is_diagnostic_artifact"):
        return False
    if ref is not None and path in {norm_path(p) for p in ref.get("patch_files", set())}:
        return True
    return not e.get("created_by_agent", False) or is_nested_product_source(path)


def text_mentions_reference_tests(e, ref):
    text = (e.get("text", "") + " " + e.get("path", "")).lower()
    for p in ref.get("test_files", set()):
        p = norm_path(p).lower()
        if p and (p in text or p.rsplit("/", 1)[-1] in text):
            return True
    for t in ref.get("fail_tests", []):
        t = str(t).lower()
        if t and t in text:
            return True
    return False


def is_reproduction_event(e, ref):
    text = (e.get("text", "") + " " + e.get("path", "") + " " + e.get("cue", "")).lower()
    path = norm_path(e.get("path", "")).lower()
    base = path.rsplit("/", 1)[-1]
    if e.get("is_temp_or_test"):
        return True
    if text_mentions_reference_tests(e, ref):
        return True
    if e["action"] == "Reason":
        reason_repro_patterns = [
            r"\b(failing test|fail_to_pass|failure reproduction|reproduce|reproduction|repro)\b",
            r"\b(assertionerror|traceback|pytest|unittest|tox|runtests)\b",
            r"\btest_[a-zA-Z0-9_]+",
            r"\btests?/",
        ]
        return any(re.search(p, text) for p in reason_repro_patterns)
    repro_patterns = [
        r"\b(pytest|unittest|tox|nosetests|runtests|test runner)\b",
        r"\b(failing test|fail_to_pass|failure reproduction|reproduce|reproduction|repro)\b",
        r"\b(assertionerror|traceback|observed failure)\b",
        r"\btest_[a-zA-Z0-9_]+",
        r"\btests?/",
    ]
    if any(re.search(p, text) for p in repro_patterns):
        return True
    if base.startswith("test_") or base.endswith("_test.py") or "test" in base and base.endswith(".py"):
        return True
    return False


def is_source_exploration(e):
    if e.get("is_source_path"):
        return True
    if e["action"] not in {"Read", "Search"}:
        return False
    text = (e.get("text", "") + " " + e.get("path", "")).lower()
    source_cues = [
        r"\b(class|def|function|method|symbol|implementation|logic|call|caller|callee)\b",
        r"\b\.py\b|\b\.java\b|\b\.js\b|\b\.ts\b|\b\.cpp\b|\b\.c\b",
    ]
    return any(re.search(p, text) for p in source_cues)


def is_validation_reason(e):
    if e["action"] != "Reason":
        return False
    text = (e.get("text", "") + " " + e.get("cue", "")).lower()
    validation_cues = [
        r"\b(validate|validation|verify|verified|test result|test output)\b",
        r"\b(pytest|unittest|tox|runtests|lint|build)\b",
        r"\b(pass(?:ed|es)?|fail(?:ed|ing|ures)?|error|traceback|assertionerror)\b",
        r"\b(exit code|all tests|remaining failure|still failing|now passes)\b",
    ]
    return any(re.search(p, text) for p in validation_cues)


def is_validation_event(e):
    if e["action"] == "Run" or e.get("executes"):
        return True
    if is_validation_reason(e):
        return True
    return e.get("is_diagnostic_artifact", False) and e["action"] in EDIT_ACTIONS


def assign_subtasks(events, ref=None):
    if not events:
        return []
    ref = ref or {"test_files": set(), "fail_tests": []}
    patch_indices = [i for i, e in enumerate(events) if is_patch_edit(e, ref)]
    first_patch = patch_indices[0] if patch_indices else None
    validation_indices = [
        i
        for i, e in enumerate(events)
        if first_patch is not None and i > first_patch and is_validation_event(e)
    ]
    pre_patch_end = first_patch if first_patch is not None else len(events)
    pre_repro = [i for i, e in enumerate(events[:pre_patch_end]) if is_reproduction_event(e, ref)]
    first_repro = pre_repro[0] if pre_repro else None
    has_pre_repro = first_repro is not None
    labels = []
    current = "Problem Understanding"
    seen_reproduction = False
    seen_validation = False
    for i, e in enumerate(events):
        action = e["action"]
        if first_patch is None or i < first_patch:
            repro_event = is_reproduction_event(e, ref)
            source_event = is_source_exploration(e) and not repro_event
            if repro_event:
                label = "Failure Reproduction"
                seen_reproduction = True
            elif source_event:
                if seen_reproduction or not has_pre_repro:
                    label = "Fault Localization"
                else:
                    label = "Problem Understanding"
            elif current == "Failure Reproduction" and action == "Reason":
                label = "Failure Reproduction"
            elif current == "Fault Localization" and action in {"Read", "Search", "Reason", "Setup"}:
                label = "Fault Localization"
            elif action == "Setup":
                label = current
            elif is_patch_edit(e, ref):
                label = "Patch Construction"
            else:
                label = current
        else:
            if is_patch_edit(e, ref):
                label = "Patch Refinement" if seen_validation else "Patch Construction"
            elif is_validation_event(e):
                label = "Patch Validation"
                seen_validation = True
            elif action in {"Read", "Search", "Reason"}:
                label = "Patch Validation" if seen_validation else "Patch Construction"
            elif action == "Setup":
                label = "Patch Validation" if seen_validation else "Patch Construction"
            else:
                label = "Patch Validation" if seen_validation else "Patch Construction"
        labels.append(label)
        current = label
    return absorb_patch_context(events, labels)


def absorb_patch_context(events, labels):
    labels = list(labels)
    for i, e in enumerate(events):
        if is_patch_edit(e) and labels[i] in {"Patch Construction", "Patch Refinement"}:
            target = labels[i]
            j = i - 1
            absorbed = 0
            while j >= 0 and absorbed < 2:
                if labels[j] in {"Patch Validation", "Fault Localization", "Problem Understanding"} and events[j]["action"] in {"Read", "Search", "Reason"}:
                    labels[j] = target
                    absorbed += 1
                    j -= 1
                else:
                    break
    return labels


def compress_actions(actions):
    out = []
    for action in actions:
        if out and out[-1].rstrip("+") == action:
            if not out[-1].endswith("+"):
                out[-1] += "+"
        else:
            out.append(action)
    return " -> ".join(out)


def token_set(lines):
    toks = set()
    for line in lines:
        toks.update(t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", line) if len(t) >= 3)
    return toks


def segment_text(events):
    return "\n".join(e.get("text", "") for e in events)


def event_relevant_to_tests(e, ref):
    text = (e.get("text", "") + " " + e.get("path", "")).lower()
    test_files = {norm_path(x).lower() for x in ref["test_files"]}
    fail_tests = [x.lower() for x in ref["fail_tests"]]
    if any(tf and tf in text for tf in test_files):
        return True
    if any(ft and ft in text for ft in fail_tests):
        return True
    return False


def text_mentions_reference_patch(text, ref):
    low = (text or "").lower()
    for p in ref["patch_files"]:
        p = norm_path(p).lower()
        if p and (p in low or p.rsplit("/", 1)[-1] in low):
            return True
    oracle_terms = token_set({ln.lower() for lines in ref["added"].values() for ln in lines})
    oracle_terms |= token_set({ln.lower() for lines in ref["removed"].values() for ln in lines})
    return any(len(t) >= 4 and t in low for t in oracle_terms)


def has_blocked_feedback(events):
    return any(e.get("blocked") or e.get("outcome") == "unknown" for e in events)


def edit_overlap_with_reference(e, ref):
    p = norm_path(e.get("path", ""))
    if p not in ref["patch_files"]:
        return False
    old_new = token_set([e.get("old_str", ""), e.get("new_str", "")])
    if not old_new:
        return True
    oracle = token_set(ref["added"].get(p, set()) | ref["removed"].get(p, set()))
    return bool(old_new & oracle)


COMMON_CODE_TOKENS = {
    "self",
    "return",
    "else",
    "elif",
    "true",
    "false",
    "none",
    "raise",
    "error",
    "value",
    "name",
    "type",
    "class",
    "def",
    "import",
    "from",
    "with",
    "try",
    "except",
}


def meaningful_tokens(lines):
    return {
        token
        for token in token_set(lines)
        if token.lower() not in COMMON_CODE_TOKENS
    }


def overlap_fraction(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def normalized_lines(text):
    return {line.strip() for line in str(text or "").splitlines() if line.strip()}


def changed_lines(old_text, new_text):
    old_lines = [line.strip() for line in str(old_text or "").splitlines()]
    new_lines = [line.strip() for line in str(new_text or "").splitlines()]
    old_changed = set()
    new_changed = set()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag != "equal":
            old_changed.update(line for line in old_lines[old_start:old_end] if line)
            new_changed.update(line for line in new_lines[new_start:new_end] if line)
    return old_changed, new_changed


def edit_alignment(e, ref):
    path = norm_path(e.get("path", ""))
    if path not in ref.get("patch_files", set()):
        return {
            "path": 0,
            "positive": 0,
            "negative": 1,
            "positive_score": 0.0,
            "negative_score": 1.0,
            "content_known": bool(e.get("old_str") or e.get("new_str")),
            "basis": "unrelated source",
        }
    old_lines, new_lines = changed_lines(e.get("old_str", ""), e.get("new_str", ""))
    added_lines = normalized_lines("\n".join(ref.get("added", {}).get(path, set())))
    removed_lines = normalized_lines("\n".join(ref.get("removed", {}).get(path, set())))
    added_only = added_lines - removed_lines
    removed_only = removed_lines - added_lines
    positive_exact = len((old_lines & removed_only) | (new_lines & added_only))
    negative_exact = len((old_lines & added_only) | (new_lines & removed_only))
    old_tokens = meaningful_tokens(old_lines)
    new_tokens = meaningful_tokens(new_lines)
    added_tokens = meaningful_tokens(added_only)
    removed_tokens = meaningful_tokens(removed_only)
    positive_tokens = len((old_tokens & removed_tokens) | (new_tokens & added_tokens))
    negative_tokens = len((old_tokens & added_tokens) | (new_tokens & removed_tokens))
    positive = positive_exact + (1 if positive_tokens >= 2 else 0)
    negative = negative_exact + (1 if negative_tokens >= 2 else 0)
    positive_score = overlap_fraction(old_tokens, removed_tokens) + overlap_fraction(new_tokens, added_tokens)
    negative_score = overlap_fraction(old_tokens, added_tokens) + overlap_fraction(new_tokens, removed_tokens)
    content_known = bool(old_lines or new_lines)
    if positive:
        basis = "reference direction"
    elif negative:
        basis = "opposes reference direction"
    else:
        basis = "reference file, effect unclear"
    return {
        "path": 1,
        "positive": positive,
        "negative": negative,
        "positive_score": positive_score,
        "negative_score": negative_score,
        "content_known": content_known,
        "basis": basis,
    }


def validation_state(events):
    state = "unknown"
    for event in events:
        if event.get("action") == "Run" or event.get("executes"):
            if event.get("outcome") in {"pass", "fail"}:
                state = event["outcome"]
    return state


def pr_effect(events, previous_validation, next_validation, ref):
    alignments = [edit_alignment(event, ref) for event in events if is_patch_edit(event)]
    positive = sum(item["positive"] for item in alignments)
    negative = sum(item["negative"] for item in alignments)
    positive_score = sum(item["positive_score"] for item in alignments)
    negative_score = sum(item["negative_score"] for item in alignments)
    # Validation transitions are deliberately not used as primary PR labels.
    # Across the public trajectories, adjacent PV segments usually execute
    # different tests, so a raw fail-to-pass comparison is not longitudinal.
    if positive_score > negative_score + 0.05:
        return "+", "edit follows reference direction"
    if negative_score > positive_score + 0.05:
        return "-", "edit opposes reference direction"
    if alignments and all(item["path"] == 0 for item in alignments):
        return "-", "source edit outside reference files"
    if alignments and any(item["path"] for item in alignments):
        if any(item["content_known"] for item in alignments):
            return "+", "reference target without opposing decisive evidence"
        return "?", "refinement content unavailable"
    return "?", "insufficient refinement evidence"


def oracle_outcome(subtask, events, ref):
    paths = {norm_path(e.get("path", "")) for e in events if e.get("path")}
    source_paths = {p for p in paths if is_source_like(p, ref)}
    text = segment_text(events).lower()
    has_run = any(e["action"] == "Run" or e.get("executes") for e in events)
    has_concrete_action = any(e["action"] in {"Read", "Search", "Run", "Add", "Revise", "Remove"} for e in events)

    if subtask == "Problem Understanding":
        if not any(e["action"] == "Reason" for e in events):
            return "?" if not has_concrete_action else "-"
        return "+" if text_mentions_reference_patch(text, ref) else "-"

    if subtask == "Failure Reproduction":
        relevant = any(event_relevant_to_tests(e, ref) for e in events)
        has_failure_signal = any(e.get("outcome") == "fail" for e in events)
        has_test_or_repro_material = any(e.get("is_temp_or_test") for e in events) or bool(
            re.search(r"\b(pytest|unittest|tox|runtests|assertionerror|traceback|repro|reproduce|failing test)\b", text)
        )
        if relevant or has_failure_signal:
            return "+"
        if has_run or has_test_or_repro_material:
            return "-"
        return "?"

    if subtask == "Fault Localization":
        if source_paths & ref["patch_files"]:
            return "+"
        if source_paths or has_concrete_action:
            return "-"
        return "?"

    if subtask in {"Patch Construction", "Patch Refinement"}:
        edits = [e for e in events if is_patch_edit(e)]
        if not edits:
            return "?"
        if any(norm_path(e.get("path", "")) in ref["patch_files"] for e in edits):
            return "+"
        return "-"

    if subtask == "Patch Validation":
        runs = [e for e in events if e["action"] == "Run" or e.get("executes")]
        if any(event_relevant_to_tests(e, ref) for e in runs):
            return "+"
        if any(e.get("outcome") in {"pass", "fail"} for e in runs):
            return "-"
        if runs or has_concrete_action:
            return "?" if has_blocked_feedback(events) and not runs else "-"
        return "?"

    return "?"


def build_segments(events, labels, ref):
    segments = []
    if not events:
        return segments
    start = 0
    for i in range(1, len(events)):
        if labels[i] != labels[i - 1]:
            segments.append(make_segment(events[start:i], labels[i - 1], len(segments) + 1, ref))
            start = i
    segments.append(make_segment(events[start:], labels[-1], len(segments) + 1, ref))
    apply_pr_outcomes(segments, events, ref)
    return segments


def apply_pr_outcomes(segments, events, ref):
    for index, segment in enumerate(segments):
        if segment["subtask_type"] != "Patch Refinement":
            continue
        previous = next(
            (candidate for candidate in reversed(segments[:index]) if candidate["subtask_type"] == "Patch Validation"),
            None,
        )
        following = next(
            (candidate for candidate in segments[index + 1 :] if candidate["subtask_type"] == "Patch Validation"),
            None,
        )
        previous_events = events[previous["start_event"] : previous["end_event"] + 1] if previous else []
        following_events = events[following["start_event"] : following["end_event"] + 1] if following else []
        current_events = events[segment["start_event"] : segment["end_event"] + 1]
        outcome, basis = pr_effect(current_events, previous_events, following_events, ref)
        segment["local_outcome"] = outcome
        segment["local_outcome_basis"] = basis


def make_segment(events, subtask, index, ref):
    actions = [e["action"] for e in events]
    paths = sorted({e.get("path") for e in events if e.get("path")})
    return {
        "subtask_index": index,
        "subtask_code": SUBTASK_CODES[subtask],
        "subtask_type": subtask,
        "start_event": events[0]["event_index"],
        "end_event": events[-1]["event_index"],
        "n_events": len(events),
        "action_sequence": compress_actions(actions),
        "actions_raw": " -> ".join(actions),
        "local_outcome": oracle_outcome(subtask, events, ref),
        "local_outcome_basis": "",
        "has_reason": any(e["action"] == "Reason" for e in events),
        "has_read": any(e["action"] == "Read" for e in events),
        "has_search": any(e["action"] == "Search" for e in events),
        "has_run": any(e["action"] == "Run" or e.get("executes") for e in events),
        "has_patch_edit": any(is_patch_edit(e) for e in events),
        "n_product_source_edits": sum(is_patch_edit(e) for e in events),
        "n_diagnostic_artifacts": sum(e.get("is_diagnostic_artifact", False) for e in events),
        "paths": ";".join(paths[:12]),
    }


def load_outcomes(root):
    return prof.load_outcomes(root)


def load_all(root, refs):
    outcomes = load_outcomes(root)
    extractors = {
        "lingxi": (root / "data/raw/lingxi", "*.traj", extract_lingxi),
        "moatless": (root / "data/raw/moatless", "*.json", extract_moatless),
        "openhands": (root / "data/raw/openhands", "*.json", extract_openhands),
    }
    for agent, (directory, pattern, extractor) in extractors.items():
        for path in sorted(directory.glob(pattern)):
            instance_id = path.stem
            ref = refs.get(instance_id)
            if not ref:
                continue
            events = extractor(path)
            for i, e in enumerate(events):
                e["event_index"] = i
            annotate_event_provenance(events, ref)
            labels = assign_subtasks(events, ref)
            segments = build_segments(events, labels, ref) if events else []
            yield agent, instance_id, instance_id in outcomes[agent], events, segments


def count_vr_loops(segments):
    loops = 0
    prev = None
    for seg in segments:
        cur = seg["subtask_type"]
        if prev == "Patch Validation" and cur == "Patch Refinement":
            loops += 1
        prev = cur
    return loops


def canonical_path(segments):
    return " -> ".join(s["subtask_code"] for s in segments)


def composition(segments):
    present = {s["subtask_type"] for s in segments}
    return " + ".join(SUBTASK_CODES[s] for s in SUBTASKS if s in present)


def pct(n, d):
    return 0.0 if d == 0 else 100.0 * n / d


def rr(resolved, n):
    return 0.0 if n == 0 else resolved / n


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def summarize(rows, keys):
    acc = defaultdict(lambda: {"n": 0, "resolved": 0})
    for r in rows:
        k = tuple(r[x] for x in keys)
        acc[k]["n"] += 1
        acc[k]["resolved"] += int(r.get("resolved", 0))
    out = []
    for k, v in sorted(acc.items(), key=lambda item: item[0]):
        row = {name: val for name, val in zip(keys, k)}
        row.update(v)
        row["resolved_rate"] = f"{rr(v['resolved'], v['n']):.3f}"
        out.append(row)
    return out


def distribution(rows, keys, total_key):
    acc = Counter(tuple(r[k] for k in keys) for r in rows)
    totals = Counter()
    idx = keys.index(total_key)
    for key, n in acc.items():
        totals[key[idx]] += n
    out = []
    for key, n in sorted(acc.items(), key=lambda item: item[0]):
        row = {name: val for name, val in zip(keys, key)}
        row["n"] = n
        row["share"] = f"{pct(n, totals[key[idx]]):.1f}%"
        out.append(row)
    return out


def wide_agent_action(action_rows):
    acc = defaultdict(Counter)
    for r in action_rows:
        acc[r["agent"]][r["action"]] += 1
    rows = []
    for agent in ["lingxi", "moatless", "openhands"]:
        total = sum(acc[agent].values())
        row = {"agent": agent, "total": total}
        for a in ACTIONS:
            row[a] = acc[agent][a]
            row[f"{a}_share"] = f"{pct(acc[agent][a], total):.1f}%"
        rows.append(row)
    return rows


def wide_agent_subtask_presence(traj_rows):
    acc = defaultdict(lambda: defaultdict(int))
    totals = Counter()
    for r in traj_rows:
        agent = r["agent"]
        totals[agent] += 1
        for s in SUBTASKS:
            if r[f"has_{SUBTASK_CODES[s]}"]:
                acc[agent][SUBTASK_CODES[s]] += 1
    rows = []
    for agent in ["lingxi", "moatless", "openhands"]:
        row = {"agent": agent, "trajectories": totals[agent]}
        for s in SUBTASKS:
            code = SUBTASK_CODES[s]
            row[code] = f"{acc[agent][code]} / {pct(acc[agent][code], totals[agent]):.1f}%"
        rows.append(row)
    return rows


def md_table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return lines


def main():
    root = ROOT
    out = Path(os.environ.get("PRE12_OUT_DIR", root / "data/processed/pre12"))
    out.mkdir(parents=True, exist_ok=True)
    refs = load_reference(root, out)

    action_rows = []
    subtask_rows = []
    traj_rows = []

    for agent, instance_id, resolved, events, segments in load_all(root, refs):
        action_counts = Counter(e["action"] for e in events)
        for e in events:
            action_rows.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": int(resolved),
                    "event_index": e["event_index"],
                    "action": e["action"],
                    "cue": e.get("cue", ""),
                    "command": e.get("command", ""),
                    "outcome": e.get("outcome", ""),
                    "path": e.get("path", ""),
                    "old_str_len": len(e.get("old_str", "")),
                    "new_str_len": len(e.get("new_str", "")),
                    "is_patch_edit": int(is_patch_edit(e)),
                    "is_temp_or_test": int(e.get("is_temp_or_test", False)),
                    "is_file_creation": int(e.get("is_file_creation", False)),
                    "created_by_agent": int(e.get("created_by_agent", False)),
                    "is_diagnostic_path": int(e.get("is_diagnostic_path", False)),
                    "is_source_path": int(e.get("is_source_path", False)),
                    "is_diagnostic_artifact": int(e.get("is_diagnostic_artifact", False)),
                    "is_product_source_edit": int(e.get("is_product_source_edit", False)),
                }
            )
        for seg in segments:
            subtask_rows.append({"agent": agent, "instance_id": instance_id, "resolved": int(resolved), **seg})
        has_pc = any(s["subtask_type"] == "Patch Construction" for s in segments)
        has_pv = any(s["subtask_type"] == "Patch Validation" for s in segments)
        traj_rows.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                "n_events": len(events),
                "n_subtasks": len(segments),
                "distinct_subtask_types": len({s["subtask_type"] for s in segments}),
                "complete_repair": int(has_pc and has_pv),
                "validation_refinement_loops": count_vr_loops(segments),
                "composition": composition(segments),
                "canonical_path": canonical_path(segments),
                **{f"has_{SUBTASK_CODES[s]}": int(any(x["subtask_type"] == s for x in segments)) for s in SUBTASKS},
                **{f"action_count_{a.lower()}": action_counts[a] for a in ACTIONS},
            }
        )

    write_csv(out / "pre12_actions.csv", action_rows)
    write_csv(out / "pre12_subtasks.csv", subtask_rows)
    write_csv(out / "pre12_trajectories.csv", traj_rows)
    write_csv(out / "pre12_agent_action_wide.csv", wide_agent_action(action_rows))
    write_csv(out / "pre12_agent_subtask_presence.csv", wide_agent_subtask_presence(traj_rows))
    write_csv(out / "pre12_local_outcomes.csv", summarize(subtask_rows, ["subtask_code", "local_outcome"]))
    write_csv(out / "pre12_agent_local_outcomes.csv", summarize(subtask_rows, ["agent", "subtask_code", "local_outcome"]))
    write_csv(out / "pre12_agent_action_distribution.csv", distribution(action_rows, ["agent", "action"], "agent"))
    write_csv(out / "pre12_agent_subtask_distribution.csv", distribution(subtask_rows, ["agent", "subtask_code"], "agent"))
    complete = [r for r in traj_rows if r["complete_repair"]]
    write_csv(out / "pre12_distinct_subtasks.csv", summarize(complete, ["distinct_subtask_types"]))
    write_csv(out / "pre12_validation_refinement_loops.csv", summarize(complete, ["validation_refinement_loops"]))
    pr_rows = [r for r in subtask_rows if r["subtask_code"] == "PR"]
    pr_quality = [
        {"metric": "pr_records", "value": len(pr_rows)},
        {"metric": "pr_diagnostic_artifact_records", "value": sum(int(r["n_diagnostic_artifacts"]) for r in pr_rows)},
        {"metric": "pr_zero_product_source_edit_records", "value": sum(int(r["n_product_source_edits"]) == 0 for r in pr_rows)},
        {"metric": "pr_unknown_records", "value": sum(r["local_outcome"] == "?" for r in pr_rows)},
        {
            "metric": "pr_unknown_share",
            "value": f"{rr(sum(r['local_outcome'] == '?' for r in pr_rows), len(pr_rows)):.4f}",
        },
    ]
    write_csv(out / "pre12_pr_quality.csv", pr_quality)

    total_resolved = sum(r["resolved"] for r in traj_rows)
    report = []
    report.append("# Pre 12.0 Recomputed Statistics\n")
    report.append("Taxonomy version: pre12_frfl_prdelta_reason2_outcome3\n")
    report.append(f"Trajectories: {len(traj_rows)}; resolved: {total_resolved}; resolved rate: {rr(total_resolved, len(traj_rows)):.3f}\n")
    report.append(f"Action records: {len(action_rows)}\n")
    report.append(f"Subtask records: {len(subtask_rows)}\n")
    report.append(f"Complete repair trajectories (PC + PV): {sum(r['complete_repair'] for r in traj_rows)}\n")
    report.append("## PR Quality Checks\n")
    report.extend(md_table(pr_quality, ["metric", "value"]))
    report.append("")
    report.append("## Agent + Action\n")
    cols = ["agent"] + ACTIONS + ["total"]
    report.extend(md_table(wide_agent_action(action_rows), cols))
    report.append("")
    report.append("## Agent + Subtask Presence\n")
    report.extend(md_table(wide_agent_subtask_presence(traj_rows), ["agent", "trajectories", "PU", "FR", "FL", "PC", "PR", "PV"]))
    report.append("")
    report.append("## Oracle-aligned Local Outcomes\n")
    report.extend(md_table(summarize(subtask_rows, ["subtask_code", "local_outcome"]), ["subtask_code", "local_outcome", "n", "resolved", "resolved_rate"]))
    report.append("")
    (out / "pre12_report.md").write_text("\n".join(report), encoding="utf-8")
    print(out / "pre12_report.md")


if __name__ == "__main__":
    main()
