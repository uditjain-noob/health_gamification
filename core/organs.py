import json
import re
from pathlib import Path
from config import DATA_DIR


class OrganMapper:
    def __init__(self, organ_map_path: Path = DATA_DIR / "organ_map.json"):
        with open(organ_map_path) as f:
            data = json.load(f)
        self._organs: dict[str, dict] = data["organs"]
        self._weights: dict[str, float] = data["organ_weights"]
        # Build reverse lookup: normalized_param -> organ
        self._param_to_organ: dict[str, str] = {}
        for organ, info in self._organs.items():
            for param in info["parameters"]:
                self._param_to_organ[param.upper()] = organ
        # Critical set: normalized names
        self._critical: set[str] = set()
        for organ, info in self._organs.items():
            for param in info.get("critical", []):
                self._critical.add(param.upper())

    def _normalize(self, name: str) -> str:
        return re.sub(r"\s+", " ", name.strip().upper())

    def get_organ(self, raw_name: str) -> str:
        normalized = self._normalize(raw_name)
        # 1. Exact match
        if normalized in self._param_to_organ:
            return self._param_to_organ[normalized]
        # 2. Substring match — find longest known param that appears in raw_name
        best = None
        best_len = 0
        for known_param, organ in self._param_to_organ.items():
            if known_param in normalized and len(known_param) > best_len:
                best = organ
                best_len = len(known_param)
        return best if best else "other"

    def is_critical(self, name: str) -> bool:
        normalized = self._normalize(name)
        if normalized in self._critical:
            return True
        return any(c in normalized for c in self._critical)

    def get_organ_weight(self, organ: str) -> float:
        return self._weights.get(organ, 0.0)

    def get_organ_emoji(self, organ: str) -> str:
        return self._organs.get(organ, {}).get("emoji", "🔬")
