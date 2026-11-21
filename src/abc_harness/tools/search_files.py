"""Find files by name and lines by regular expression, in the paths read_file may read.

One tool covers both searches: with `pattern`, it returns matching lines as
`path:line: text`; without it, it lists the files whose names match `glob`.
Each returned path can be passed to read_file as is. Read-only, like read_file.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from abc_harness.tools.base import ToolContext, ToolError
from abc_harness.tools.paths import agent_path, resolve

DEFAULT_RESULTS = 50
MAX_RESULTS = 200
MAX_FILE_BYTES = 2_000_000  # larger files are skipped and counted
MAX_LINE_CHARS = 200
MAX_PATTERN_CHARS = 300
SKIP_DIRS = {".git", "__pycache__", ".gradle", "node_modules", ".venv"}

SPEC: dict[str, Any] = {
    "name": "search_files",
    "description": "Search the files read_file can read: the simulator source (`source/<simulator>/`), example "
    "plans (`examples/`), this task's directory (`task/`, including saved paper texts and your edited "
    "source), and earlier tasks of the conversation (`previous/<task_id>/`). With `pattern`, returns matching lines as `path:line: text`; without it, lists files whose names "
    "match `glob`. Use it to find where something is defined or used, then read that part with read_file "
    "and an offset, instead of paging through whole folders.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder or file to search, e.g. 'source/simblock/' or "
                     "'task/papers/'."},
            "pattern": {"type": "string", "description": "Python regular expression matched against each line, "
                        "e.g. 'sendBlock|broadcast'. Leave out to list files by name only."},
            "glob": {"type": "string", "description": "Only files whose name matches, e.g. '*.java'. Default all."},
            "ignore_case": {"type": "boolean", "description": "Default false."},
            "max_results": {"type": "integer", "description": f"Default {DEFAULT_RESULTS}, at most {MAX_RESULTS}."},
        },
        "required": ["path"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = str(args.get("path", ""))
    pattern = args.get("pattern")
    glob = str(args.get("glob") or "*")
    try:
        limit = max(1, min(int(args.get("max_results") or DEFAULT_RESULTS), MAX_RESULTS))
    except (TypeError, ValueError) as e:
        raise ToolError("max_results must be a whole number") from e
    regex = None
    if pattern:
        if len(str(pattern)) > MAX_PATTERN_CHARS:
            raise ToolError(f"pattern is longer than {MAX_PATTERN_CHARS} characters")
        try:
            regex = re.compile(str(pattern), re.IGNORECASE if args.get("ignore_case") else 0)
        except re.error as e:
            raise ToolError(f"invalid regular expression: {e}") from e
    root, target, prefix = resolve(ctx, path)
    if not target.exists():
        raise ToolError(f"nothing at {path}")
    files = [target] if target.is_file() else _files(target, glob)
    if regex is None:
        shown = [agent_path(root, prefix, f) for f in files[:limit]]
        header = f"[{len(files)} files matching {glob!r} under {path}" + (f"; showing {limit}]" if len(files) > limit else "]")
        return header + ("\n" + "\n".join(shown) if shown else "\nNo file matches.")

    hits: list[str] = []
    matched_files, total, skipped = 0, 0, 0
    for file in files:
        if file.stat().st_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        data = file.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary
        found = False
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
            if regex.search(line):
                total += 1
                found = True
                if len(hits) < limit:
                    text = line.strip()
                    text = text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 1] + "…"
                    hits.append(f"{agent_path(root, prefix, file)}:{number}: {text}")
        matched_files += found
    header = f"[{total} matching lines in {matched_files} files under {path}"
    if total > len(hits):
        header += f"; showing the first {len(hits)}, narrow the pattern or path for the rest"
    if skipped:
        header += f"; {skipped} files over {MAX_FILE_BYTES // 1_000_000} MB skipped"
    header += "]"
    return header + ("\n" + "\n".join(hits) if hits else "\nNo line matches.")


def _files(folder: Path, glob: str) -> list[Path]:
    """Files under folder whose name matches glob, in a stable order, without tool and VCS folders."""
    found = []
    for file in sorted(folder.rglob("*")):
        if any(part in SKIP_DIRS for part in file.relative_to(folder).parts[:-1]):
            continue
        if file.is_file() and not file.is_symlink() and fnmatch(file.name, glob):
            found.append(file)
    return found
