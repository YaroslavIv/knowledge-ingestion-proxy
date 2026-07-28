from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to this package's own location, not the process's current working
# directory — a relative default (e.g. "./ingestion_proxy.db") means
# launching uvicorn from a different cwd (a different terminal, a script, a
# process manager, systemd) silently starts a brand-new empty database, and
# every saved connection/login "disappears" even though nothing was deleted.
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXY_", env_file=".env")

    owui_base_url: str = "http://localhost:8080"
    owui_api_key: str = ""

    # Guards this proxy's OWN API — separate from owui_api_key above, which
    # is what the proxy uses to talk TO Open WebUI. Compatible with Open
    # WebUI's own convention: callers send `Authorization: Bearer <key>`.
    # Left empty (the default), the API stays open — matches every existing
    # deployment/test that predates this setting; set PROXY_API_KEY to
    # actually require it. Named `api_key`, not `proxy_api_key` — env_prefix
    # already adds "PROXY_", so a field literally named proxy_api_key would
    # need PROXY_PROXY_API_KEY to be set, which is not what anyone would type.
    api_key: str = ""

    db_path: str = str(_DATA_DIR / "ingestion_proxy.db")
    # Where original file bytes are cached locally so an already-committed
    # document's "existing file" pane can show the real original (Open WebUI
    # itself never receives it — see app/original_storage.py).
    originals_dir: str = str(_DATA_DIR / "originals")
    # Full version history of every generated course-module output (SCORM
    # zips etc.) — kept locally forever, even after an older version's Open
    # WebUI file is deleted to make room for the current one (see
    # app/course_generation/output_storage.py).
    course_outputs_dir: str = str(_DATA_DIR / "course_outputs")

    session_ttl_hours: int = 24
    max_upload_size_mb: int = 50

    cors_allow_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
