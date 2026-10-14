"""User settings and paths (XDG), plus loading the Gemini key from a .env file."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

APP = "leitor-voz"
DEFAULT_PORT = 47321

# Gemini's prebuilt voices.
VOICES = [
    "Sadaltager", "Charon", "Rasalgethi", "Iapetus", "Erinome", "Schedar", "Kore",
    "Orus", "Alnilam", "Achird", "Sulafat", "Vindemiatrix", "Despina", "Algieba",
    "Achernar", "Gacrux", "Zephyr", "Autonoe", "Puck", "Laomedeia", "Fenrir", "Leda",
    "Aoede", "Callirrhoe", "Umbriel", "Enceladus", "Algenib", "Pulcherrima",
    "Zubenelgenubi", "Sadachbia",
]
DEFAULT_MODEL = "gemini-3.8-flash-tts"
SPEED_MIN, SPEED_MAX = 0.5, 2.5

# Delivery only: Gemini reads the text verbatim and detects the language itself, and long
# style prompts make the voice drift.
DEFAULT_STYLE = "claro, calmo e didático, em ritmo de estudo"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / APP


def load_env() -> None:
    """Load GEMINI_API_KEY from $LEITOR_ENV_FILE or ~/.config/leitor-voz/.env.

    Variables already present in the environment win.
    """
    explicit = os.environ.get("LEITOR_ENV_FILE")
    path = Path(explicit).expanduser() if explicit else config_dir() / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


@dataclass
class Settings:
    voice: str = "Sadaltager"
    speed: float = 1.0
    model: str = DEFAULT_MODEL
    style: str = DEFAULT_STYLE
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
        if "style" in data:
            self.style = str(data["style"])[:300]

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
        # Settings saved by the OpenAI version (≤ 0.2): its voices and model don't exist here.
        if settings.voice not in VOICES:
            settings.voice = cls.voice
        if not str(settings.model).startswith("gemini"):
            settings.model = DEFAULT_MODEL
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))
