"""
Automated Offset Fetcher and Manager
Retrieves game offsets dynamically from remote text/JSON dumps,
caches them locally, and parses 'Scope::OffsetName' formats into usable integers.
"""

import json
import os
import re
import time
import urllib.request
from typing import Any, Dict, Optional


class OffsetFetcher:
    """Automated offset retriever, parser, and local cache manager."""

    DEFAULT_URL = "https://offsets.imtheo.lol/offsets.txt"

    def __init__(
        self,
        url: str = DEFAULT_URL,
        cache_file: str = "offsets_cache.json",
        cache_ttl_seconds: int = 3600,  # 1 hour cache lifespan
        auto_fetch: bool = True,
    ):
        self.url = url
        self.cache_file = cache_file
        self.cache_ttl = cache_ttl_seconds
        self.offsets: Dict[str, int] = {}

        if auto_fetch:
            self.load()

    def load(self, force_refresh: bool = False) -> bool:
        """Loads offsets from local cache if valid, otherwise fetches fresh from URL."""
        if not force_refresh and self._is_cache_valid():
            print(f"[OffsetFetcher] Loading cached offsets ({self.cache_file})...")
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    self.offsets = {
                        k: int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v)
                        for k, v in cached_data.items()
                    }
                return True
            except Exception as e:
                print(f"[OffsetFetcher] Cache read failed ({e}), fetching fresh...")

        return self.fetch_remote()

    def fetch_remote(self) -> bool:
        """Downloads raw offsets from the web endpoint."""
        print(f"[OffsetFetcher] Fetching offsets from {self.url}...")
        try:
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                raw_data = response.read().decode("utf-8")

            self.offsets = self._parse(raw_data)
            self._save_cache()
            print(f"[OffsetFetcher] Successfully parsed {len(self.offsets)} offsets.")
            return True
        except Exception as e:
            print(f"[OffsetFetcher] Error fetching remote offsets: {e}")
            return False

    def _parse(self, content: str) -> Dict[str, int]:
        """
        Parses raw text content into a clean dictionary of key -> int offsets.
        Supports:
        - Scope resolution syntax: DataModel::PlaceVersion = 0x120
        - C++ namespaces: namespace DataModel { constexpr uintptr_t PlaceVersion = 0x120; }
        - Key-Value pairs & JSON dumps
        """
        parsed: Dict[str, int] = {}
        content_trimmed = content.strip()

        # Format 1: Direct JSON Payload
        if content_trimmed.startswith("{") or content_trimmed.startswith("["):
            try:
                data = json.loads(content_trimmed)
                self._flatten_json(data, "", parsed)
                return parsed
            except json.JSONDecodeError:
                pass

        # Format 2: C++ Namespace / Scope Text Syntax
        current_namespace = ""

        for line in content.splitlines():
            line = line.strip()

            if not line or line.startswith("//") or line.startswith("#"):
                continue

            # Detect C++ namespace block start (e.g., namespace DataModel {)
            ns_match = re.match(r"namespace\s+([A-Za-z0-9_]+)\s*\{?", line)
            if ns_match:
                current_namespace = ns_match.group(1)
                continue

            # Detect closing brace
            if line == "}" or line.startswith("};"):
                current_namespace = ""
                continue

            # Regex match key-value pairs (e.g. DataModel::PlaceVersion = 0x120)
            kv_match = re.search(
                r"(?:inline\s+|constexpr\s+|uintptr_t\s+|const\s+|static\s+)*"
                r"([A-Za-z0-9_:]+)\s*[:=]\s*(0x[0-9a-fA-F]+|[0-9]+)",
                line,
            )

            if kv_match:
                key, val_str = kv_match.group(1), kv_match.group(2)

                # Append current namespace if key is not already fully qualified
                if current_namespace and "::" not in key:
                    full_key = f"{current_namespace}::{key}"
                else:
                    full_key = key

                # Convert hex (0x...) or decimal string to int
                val = int(val_str, 16) if val_str.lower().startswith("0x") else int(val_str)
                parsed[full_key] = val

        return parsed

    def _flatten_json(self, data: Any, prefix: str, out_dict: Dict[str, int]):
        """Flattens nested JSON structures into 'Namespace::Key' strings."""
        if isinstance(data, dict):
            for k, v in data.items():
                new_prefix = f"{prefix}::{k}" if prefix else k
                self._flatten_json(v, new_prefix, out_dict)
        elif isinstance(data, (int, str)):
            if isinstance(data, str) and (data.startswith("0x") or data.isdigit()):
                val = int(data, 16) if data.startswith("0x") else int(data)
                out_dict[prefix] = val
            elif isinstance(data, int):
                out_dict[prefix] = data

    def _is_cache_valid(self) -> bool:
        """Checks if local cache file exists and hasn't expired."""
        if not os.path.exists(self.cache_file):
            return False
        file_age = time.time() - os.path.getmtime(self.cache_file)
        return file_age < self.cache_ttl

    def _save_cache(self) -> None:
        """Saves current offsets to disk formatted as hex values."""
        try:
            formatted = {k: f"0x{v:X}" for k, v in self.offsets.items()}
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(formatted, f, indent=2)
        except Exception as e:
            print(f"[OffsetFetcher] Failed to write cache: {e}")

    # -------------------------------------------------------------------------
    # Public API / Accessors
    # -------------------------------------------------------------------------
    def get(self, key: str, default: Optional[int] = None) -> Optional[int]:
        """
        Get offset by full key.
        Example: fetcher.get("DataModel::PlaceVersion")
        """
        return self.offsets.get(key, default)

    def get_offset(self, scope: str, name: str, default: Optional[int] = None) -> Optional[int]:
        """
        Get offset using split scope and name.
        Example: fetcher.get_offset("DataModel", "PlaceVersion")
        """
        key = f"{scope}::{name}"
        return self.offsets.get(key, default)

    def __getitem__(self, key: str) -> int:
        return self.offsets[key]

    def __contains__(self, key: str) -> bool:
        return key in self.offsets
