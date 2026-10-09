"""User settings and paths (XDG), plus loading the OpenAI key from a .env file."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

APP = "leitor-voz"
DEFAULT_PORT = 47321

VOICES = [
    "marin", "cedar", "alloy", "ash", "ballad", "coral", "echo",
    "fable", "nova", "onyx", "sage", "shimmer", "verse",
]
SPEED_MIN, SPEED_MAX = 0.5, 2.5

DEFAULT_INSTRUCTIONS = (
    "Leia em português do Brasil, com tom claro, calmo e didático, em ritmo de estudo. "
    "Pronuncie corretamente termos e siglas médicas; leia números, doses e unidades por extenso."
)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / APP


def load_env() -> None:
    """Load OPENAI_API_KEY from $LEITOR_ENV_FILE or ~/.config/leitor-voz/.env.

    Variables already present in the environment win.
    """
    explicit = os.environ.get("LEITOR_ENV_FILE")
    path = Path(explicit).expanduser() if explicit else config_dir() / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


@dataclass
class Settings:
    voice: str = "marin"
    speed: float = 1.0
    model: str = "gpt-4o-mini-tts"
    instructions: str = DEFAULT_INSTRUCTIONS
    port: int = DEFAULT_PORT
    cache_mb: int = 300
    output_device: str = ""  # audio output id; "" = automatic

    def update(self, data: dict) -> None:
        """Apply a partial update, validating the user-editable fields."""
        if "voice" in data:
            if data["voice"] not in VOICES:
                raise ValueError(f"voz desconhecida: {data['voice']!r}")
            self.voice = data["voice"]
        if "speed" in data:
            speed = float(data["speed"])
            if not SPEED_MIN <= speed <= SPEED_MAX:
                raise ValueError(f"velocidade fora de {SPEED_MIN}–{SPEED_MAX}")
            self.speed = round(speed, 2)
        if "output_device" in data:
            self.output_device = str(data["output_device"])[:300]
        if "instructions" in data:
            self.instructions = str(data["instructions"])[:2000]

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "config.json"
        settings = cls()
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return settings
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(settings, key, value)
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))
