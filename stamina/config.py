"""Settings from environment variables, with an optional .env file in the project root."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def llm_settings() -> tuple[str, str, str]:
    base_url = os.environ.get("LLM_BASE_URL", "")
    model = os.environ.get("LLM_MODEL", "")
    key = os.environ.get("LLM_API_KEY", "")
    key_file = os.environ.get("LLM_API_KEY_FILE", "")
    if not key and key_file:
        key = Path(key_file).read_text(encoding="utf-8").strip()
    missing = [n for n, v in (("LLM_BASE_URL", base_url), ("LLM_MODEL", model), ("LLM_API_KEY", key)) if not v]
    if missing:
        raise RuntimeError(f"missing settings: {', '.join(missing)} (see .env.example)")
    return base_url, model, key
