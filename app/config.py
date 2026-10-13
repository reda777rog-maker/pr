"""Configuration lue depuis les variables d'environnement (et un fichier .env optionnel)."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans écraser l'environnement existant."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    claude_model: str
    replicate_token: str
    replicate_image_model: str
    replicate_video_model: str
    films_dir: Path

    @property
    def has_replicate(self) -> bool:
        return bool(self.replicate_token)


def get_settings() -> Settings:
    films_dir = Path(os.environ.get("FILMS_DIR", "films"))
    if not films_dir.is_absolute():
        films_dir = ROOT / films_dir
    return Settings(
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        replicate_token=os.environ.get("REPLICATE_API_TOKEN", ""),
        replicate_image_model=os.environ.get("REPLICATE_IMAGE_MODEL", "black-forest-labs/flux-schnell"),
        replicate_video_model=os.environ.get("REPLICATE_VIDEO_MODEL", "minimax/video-01"),
        films_dir=films_dir,
    )
