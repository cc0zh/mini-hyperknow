"""Model-facing workspace tool definitions, separate from their executors."""

from __future__ import annotations

from .manager import ToolDefinition
from .shared import MAX_FILE_BYTES, MAX_PREVIEW_CHARS
from .workspace_executor import WorkspaceExecutors


def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def _string(**constraints) -> dict:
    return {"type": "string", **constraints}


def _integer(minimum: int, maximum: int) -> dict:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def workspace_definitions(executor: WorkspaceExecutors) -> list[ToolDefinition]:
    path = _string(minLength=1, maxLength=4096)
    return [
        ToolDefinition(
            "read_file", "Read UTF-8 text with 1-based offset/limit and line numbers. "
            "Read before editing or overwriting. Large files have an explicit safety limit; "
            "registered output archives are also readable. Use targeted pages, not entire files.",
            _schema({"path": path, "offset": _integer(1, 10_000_000), "limit": _integer(1, 2000),
                     "max_chars": _integer(1, MAX_PREVIEW_CHARS)}, ("path",)), executor.read_file,
        ),
        ToolDefinition(
            "list_files", "List immediate workspace directory entries; symlinks are not traversed.",
            _schema({"path": path, "limit": _integer(1, 2000)}), executor.list_files,
        ),
        ToolDefinition(
            "grep", "Search file contents with ripgrep, returning path:line:text. "
            "Use glob for filenames instead. Honors rg ignore rules (explicit globs may override "
            "ignores), never follows symlinks.",
            _schema({"path": path, "pattern": _string(minLength=1, maxLength=10_000),
                     "glob": _string(maxLength=4096), "context": _integer(0, 20),
                     "max_results": _integer(1, 2000), "literal": {"type": "boolean"},
                     "ignore_case": {"type": "boolean"}}, ("pattern",)), executor.grep,
        ),
        ToolDefinition(
            "glob", "Find workspace file paths using ripgrep filename globs and ignore rules. "
            "Use grep for file contents instead; no symlink traversal.",
            _schema({"path": path, "pattern": _string(minLength=1, maxLength=4096),
                     "max_results": _integer(1, 2000)}, ("pattern",)), executor.glob,
        ),
        ToolDefinition(
            "edit_file", "Exactly replace old_string; it must be unique unless replace_all=true. "
            "Read first: changed files and symlink writes are refused. Requires approval.",
            _schema({"path": path, "old_string": _string(minLength=1, maxLength=MAX_FILE_BYTES),
                     "new_string": _string(maxLength=MAX_FILE_BYTES),
                     "replace_all": {"type": "boolean"}}, ("path", "old_string", "new_string")),
            executor.edit_file, is_read_only=False, requires_approval=True,
        ),
        ToolDefinition(
            "write_file", "Atomically create or overwrite a UTF-8 workspace file. Overwrite requires "
            "a prior read and unchanged digest. Prefer edit_file for local changes. Requires approval.",
            _schema({"path": path, "content": _string(maxLength=MAX_FILE_BYTES)}, ("path", "content")),
            executor.write_file, is_read_only=False, requires_approval=True,
        ),
        ToolDefinition(
            "bash", "Run a command in an explicitly selected installed shell, with workspace cwd. "
            "NOT an OS sandbox: approved commands have host-user permissions, including outside "
            "the workspace and network. Always requires approval. Shell state does not persist. "
            "Use read_file/glob/grep for inspection. Output is streamed to a bounded archive; "
            "timeout/cancellation terminates the process tree. Inherited credentials are stripped.",
            _schema({"shell": _string(enum=["powershell", "pwsh", "cmd", "sh", "bash"]),
                     "command": _string(minLength=1, maxLength=100_000), "cwd": path,
                     "timeout": {"type": "number", "minimum": 0.05, "maximum": 600}},
                    ("shell", "command")), executor.bash, is_read_only=False, requires_approval=True,
        ),
    ]
