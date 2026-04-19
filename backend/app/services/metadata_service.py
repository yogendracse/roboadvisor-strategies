import json
from typing import Any

from app.core.config import METADATA_PATH


def load_metadata() -> dict[str, Any]:
    if METADATA_PATH.exists():
        with METADATA_PATH.open() as f:
            return json.load(f)
    return {}


def save_metadata(meta: dict[str, Any]) -> None:
    with METADATA_PATH.open("w") as f:
        json.dump(meta, f, indent=2)


def set_sector(label: str, sector: str) -> None:
    meta = load_metadata()
    meta[label] = {"sector": sector}
    save_metadata(meta)


def delete_entry(label: str) -> None:
    meta = load_metadata()
    meta.pop(label, None)
    save_metadata(meta)


def get_sector(label: str, default: str = "Unclassified") -> str:
    return load_metadata().get(label, {}).get("sector", default)
