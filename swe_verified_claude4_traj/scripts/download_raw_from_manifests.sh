#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$ROOT/data/official/tmp"
JOBS="${JOBS:-4}"

mkdir -p "$TMP"

download_agent() {
  local agent="$1"
  local urls_file="$ROOT/data/official/manifests/$agent.urls"
  local pending="$TMP/${agent}_raw_pending.tsv"

  if [[ ! -f "$urls_file" ]]; then
    echo "Missing manifest URL file: $urls_file" >&2
    return 1
  fi

  python3 - "$urls_file" "$pending" "$ROOT" "$agent" <<'PY'
import sys
from pathlib import Path

urls_file = Path(sys.argv[1])
pending = Path(sys.argv[2])
root = Path(sys.argv[3])
agent = sys.argv[4]
rows = []
for line in urls_file.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    url, out = line.split("\t", 1)
    # Resolve portable manifests and legacy absolute paths in this checkout.
    p = root / "data" / "raw" / agent / Path(out).name
    if not p.exists() or p.stat().st_size == 0:
        rows.append((url, str(p)))
pending.write_text("\n".join(f"{url}\t{out}" for url, out in rows) + ("\n" if rows else ""), encoding="utf-8")
print(len(rows))
PY

  local pending_count
  pending_count="$(wc -l < "$pending" | tr -d ' ')"
  echo "[$agent] pending=$pending_count jobs=$JOBS"
  if [[ "$pending_count" == "0" ]]; then
    return
  fi

  xargs -d $'\n' -a "$pending" -P "$JOBS" -L 1 bash -c '
    set -euo pipefail
    line="$1"
    url="${line%%	*}"
    out="${line#*	}"
    tmp="${out}.part"
    mkdir -p "$(dirname "$out")"
    curl -L -f -sS -C - --retry 8 --retry-all-errors --connect-timeout 20 --max-time 900 -o "$tmp" "$url"
    mv "$tmp" "$out"
  ' _
}

download_agent lingxi
download_agent moatless
download_agent openhands

python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = {
    "lingxi": ("*.traj", 500),
    "moatless": ("*.json", 500),
    "openhands": ("*.json", 500),
}
ok = True
for agent, (pattern, want) in expected.items():
    files = list((root / "data" / "raw" / agent).glob(pattern))
    print(f"{agent}: {len(files)}/{want}")
    if len(files) != want:
        ok = False
if not ok:
    raise SystemExit(1)
PY
