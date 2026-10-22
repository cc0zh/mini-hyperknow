"""Factory for opt-in workspace tools; never registered by product services."""

from __future__ import annotations

from pathlib import Path
import tempfile

from .manager import ToolManager
from .output import OutputTruncator
from .shared import Workspace
from .workspace_definitions import workspace_definitions
from .workspace_executor import WorkspaceExecutors


def create_workspace_tools(root: str | Path, *, output_dir: str | Path | None = None) -> ToolManager:
    """Create scoped file tools plus approval-gated, explicitly unsandboxed commands.

    Output archives are private local files; callers own retention and cleanup.
    Only this manager's registered archives outside root can be read back. Path
    checks and digest comparisons are best-effort against concurrent local actors,
    not a substitute for kernel isolation against hostile filesystem mutation.
    """
    directory = output_dir if output_dir is not None else tempfile.mkdtemp(prefix="agent-workspace-output-")
    workspace = Workspace(root, directory)
    truncator = OutputTruncator(output_dir=directory, on_archive=workspace.archive)
    return ToolManager(workspace_definitions(WorkspaceExecutors(workspace)), truncator=truncator)
