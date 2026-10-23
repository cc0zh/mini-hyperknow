"""Local configuration; credentials never enter public responses."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    timeout: float = 120
    tavily_api_key: str = field(default="", repr=False)

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if key == "replace-with-your-api-key":
            key = ""
        return cls(
            data_dir=Path(os.getenv("HK_DATA_DIR", "data")),
            api_key=key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            timeout=float(os.getenv("HK_MODEL_TIMEOUT_SECONDS", "120")),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        )
