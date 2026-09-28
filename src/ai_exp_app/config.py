from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    data_dir: Path
    cache_root: Path
    web_root: Path = ROOT / "web" / "dist"
    port: int = 8765

    @classmethod
    def load(cls, data_dir: Path | None = None):
        directory = Path(data_dir or os.environ.get("AI_EXP_DATA_DIR", ROOT / ".local")).resolve()
        cache = Path(os.environ.get("AI_EXP_CACHE_ROOT", ROOT / "gpu_downloads" if data_dir is None else directory / "gpu_downloads")).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return cls(directory, cache, port=int(os.environ.get("AI_EXP_PORT", "8765")))
