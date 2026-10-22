"""Bounded executors; schemas and model-facing descriptions live separately."""

from __future__ import annotations

import difflib
import heapq
import os
from pathlib import Path
import shutil
from typing import Any

from ..types import ToolResult
from .process import run_process
from .scheduler import is_cancelled
from .shared import MAX_FILE_BYTES, MAX_PREVIEW_CHARS, Workspace, check_cancelled, digest_file, is_link, read_text


class WorkspaceExecutors:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def read_file(self, args: dict[str, Any]) -> ToolResult:
        ws = self.workspace
        path = ws.path(args["path"])
        digest = digest_file(path)
        offset, limit = args.get("offset", 1), args.get("limit", 200)
        cap = args.get("max_chars", MAX_PREVIEW_CHARS)
        lines: list[str] = []
        count = 0
        truncated = False
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            line_number = 1
            while line_number < offset:
                check_cancelled()
                fragment = handle.readline(65536)
                if not fragment:
                    break
                if fragment.endswith(("\n", "\r")):
                    if fragment.endswith("\r"):
                        # newline="" recognizes standalone CR without translating
                        # it. A size-limited fragment can also split a CRLF pair;
                        # consume its LF before beginning the requested next line.
                        position = handle.tell()
                        if handle.read(1) != "\n":
                            handle.seek(position)
                    line_number += 1
            if line_number >= offset:
                for line_number in range(offset, offset + limit):
                    check_cancelled()
                    line = handle.readline(max(1, cap - count) + 1)
                    if not line:
                        break
                    rendered = f"{line_number}|{line}"
                    if len(rendered) > cap - count:
                        lines.append(rendered[:max(0, cap - count)])
                        truncated = True
                        break
                    lines.append(rendered)
                    count += len(rendered)
                truncated = truncated or bool(handle.read(1))
        if digest_file(path) != digest:
            return ToolResult(False, error="file changed during read; retry")
        ws.record_read(path, digest)
        content = "".join(lines)
        if truncated:
            marker = "\n[truncated; use offset/limit or increase max_chars within safety bounds]"
            content = (content[:cap - len(marker)] + marker if len(marker) <= cap
                       else "[truncated]"[:cap])
        return ToolResult(True, data=content)

    def list_files(self, args: dict[str, Any]) -> ToolResult:
        path = self.workspace.path(args.get("path", "."))
        limit = args.get("limit", 200)

        def entries():
            with os.scandir(path) as directory:
                for entry in directory:
                    check_cancelled()
                    kind = " [symlink; not traversed]" if is_link(Path(entry.path)) else ("/" if entry.is_dir(follow_symlinks=False) else "")
                    yield entry.name + kind

        found = heapq.nsmallest(limit + 1, entries())
        content = "\n".join(found[:limit])
        if len(found) > limit:
            content += "\n[truncated; more entries exist]"
        return ToolResult(True, data=content)

    def _ripgrep(self, arguments: list[str], limit: int) -> ToolResult:
        executable = shutil.which("rg")
        if executable is None:
            return ToolResult(False, error="ripgrep (rg) executable not found; install rg and add it to PATH")
        output = run_process([executable, *arguments], cwd=self.workspace.root,
                             output_dir=self.workspace.output_dir, timeout=10,
                             is_aborted=is_cancelled, preview_chars=MAX_PREVIEW_CHARS)
        self.workspace.archive(output.path)
        if output.status != "completed" or output.exit_code not in {0, 1}:
            return ToolResult(False, error=output.render())
        if output.exit_code == 1:
            return ToolResult(True, data="No matches.")
        lines = output.preview.splitlines()
        content = "\n".join(lines[:limit])
        preview_complete = output.bytes_written <= len(output.preview.encode("utf-8"))
        if len(lines) > limit or not preview_complete:
            content += f"\n[truncated; full search output: {output.path}]"
        return ToolResult(True, data=content)

    def grep(self, args: dict[str, Any]) -> ToolResult:
        path = self.workspace.path(args.get("path", "."))
        if not path.is_relative_to(self.workspace.root):
            return ToolResult(False, error="search is limited to workspace; read artifacts with read_file")
        relative = path.relative_to(self.workspace.root).as_posix() or "."
        argv = ["--line-number", "--with-filename", "--no-heading", "--color=never", "--no-follow"]
        if args.get("glob"):
            argv.append(f"--glob={args['glob']}")
        if args.get("literal", False):
            argv.append("--fixed-strings")
        if args.get("ignore_case", False):
            argv.append("--ignore-case")
        argv.extend(["--context", str(args.get("context", 0)), "--", args["pattern"], relative])
        return self._ripgrep(argv, args.get("max_results", 100))

    def glob(self, args: dict[str, Any]) -> ToolResult:
        path = self.workspace.path(args.get("path", "."))
        if not path.is_relative_to(self.workspace.root):
            return ToolResult(False, error="search is limited to workspace")
        relative = path.relative_to(self.workspace.root).as_posix() or "."
        return self._ripgrep(["--files", "--color=never", "--no-follow", f"--glob={args['pattern']}",
                              "--", relative], args.get("max_results", 200))

    @staticmethod
    def _diff(path: Path, before: str, after: str) -> str:
        return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                            fromfile=str(path), tofile=str(path), lineterm="\n")) or "No changes."

    def write_file(self, args: dict[str, Any]) -> ToolResult:
        ws = self.workspace
        content = args["content"]
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            return ToolResult(False, error=f"content exceeds {MAX_FILE_BYTES} byte safety limit")
        with ws.lock:
            path = ws.path(args["path"], writing=True)
            expected = ws.expected(path)
            before = read_text(path) if expected is not None else ""
            ws.atomic_write(args["path"], content, expected)
        return ToolResult(True, data=self._diff(path, before, content))

    def edit_file(self, args: dict[str, Any]) -> ToolResult:
        ws = self.workspace
        with ws.lock:
            path = ws.path(args["path"], writing=True)
            expected = ws.expected(path)
            if expected is None:
                return ToolResult(False, error="cannot edit missing file; use write_file to create it")
            before = read_text(path)
            old, new = args["old_string"], args["new_string"]
            count = before.count(old)
            if count == 0:
                return ToolResult(False, error="old_string has no exact match; read the file again")
            if count > 1 and not args.get("replace_all", False):
                return ToolResult(False, error="ambiguous old_string; provide unique context or replace_all")
            after = before.replace(old, new, -1 if args.get("replace_all", False) else 1)
            if len(after.encode("utf-8")) > MAX_FILE_BYTES:
                return ToolResult(False, error=f"edited file exceeds {MAX_FILE_BYTES} byte safety limit")
            ws.atomic_write(args["path"], after, expected)
        return ToolResult(True, data=self._diff(path, before, after))

    def bash(self, args: dict[str, Any]) -> ToolResult:
        shell = args["shell"]
        executable = shutil.which(shell)
        if executable is None:
            return ToolResult(False, error=f"explicit shell executable not found: {shell}")
        command = args["command"]
        if not command.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in command):
            return ToolResult(False, error="command is empty or contains forbidden control characters")
        if any(c.isspace() and c not in " \n\r\t" or c == "\u200b" for c in command):
            return ToolResult(False, error="command contains non-ASCII whitespace")
        flags = {"powershell": ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"],
                 "pwsh": ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"],
                 "cmd": ["/d", "/s", "/c"], "sh": ["-c"], "bash": ["--noprofile", "--norc", "-c"]}
        cwd = self.workspace.path(args.get("cwd", "."))
        if not cwd.is_relative_to(self.workspace.root):
            return ToolResult(False, error="command cwd must be inside workspace")
        output = run_process([executable, *flags[shell], command], cwd=cwd,
                             output_dir=self.workspace.output_dir, timeout=args.get("timeout", 30),
                             is_aborted=is_cancelled)
        self.workspace.archive(output.path)
        if output.status != "completed" or output.exit_code != 0:
            return ToolResult(False, error=output.render())
        return ToolResult(True, data=output.render())
