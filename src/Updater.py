import requests
from typing import Any, Dict, Optional

class OffsetManager:
    """Handles fetching, caching, and retrieving memory offsets."""
    
    _latest_offsets: Dict[str, Any] = {}
    ENDPOINT: str = "https://offsets.imtheo.lol/offsets.txt"

    @classmethod
    def update(cls, url: str = ENDPOINT, timeout: float = 10.0) -> bool:
        """Fetches the latest offsets and updates the local cache."""
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            # Attempt JSON parsing first; fall back to line-by-line key=value parsing
            try:
                cls._latest_offsets = response.json()
            except ValueError:
                cls._latest_offsets = cls._parse_text(response.text)

            return True

        except requests.RequestException as err:
            print(f"[OffsetManager] Fetch failed: {err}")
            return False

    @classmethod
    def get(cls, name: str, default: Optional[Any] = None) -> Optional[Any]:
        """Retrieves a cached offset by name."""
        return cls._latest_offsets.get(name, default)

    @staticmethod
    def _parse_text(text: str) -> Dict[str, str]:
        """Utility to parse key-value lines (e.g., 'Key: Value' or 'Key = Value')."""
        parsed = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "//")):
                continue
            
            delimiter = ":" if ":" in line else ("=" if "=" in line else None)
            if delimiter:
                key, val = line.split(delimiter, 1)
                parsed[key.strip()] = val.strip()
        return parsed