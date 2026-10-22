from .executor import read_file
from .. import ToolDefinition


read_file_tool = ToolDefinition(
    name="read_file",
    description=(
        "Read a UTF-8 text file. Use it when you need to inspect file contents; "
        "do not use it to modify files or execute commands."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the text file."},
            "max_chars": {
                "type": "integer",
                "description": "Optional maximum number of returned characters.",
                "minimum": 1,
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    handler=read_file,
)
