"""
utils/cache.py — File-based cache that persists across requests on Render.
Render free tier may use multiple processes — in-memory cache doesn't share.
This writes to /tmp which is shared within the same instance.
"""

import json
import time
import os
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = "/tmp/tradeready_cache"


class Cache:
    def __init__(self, default_ttl: int = 180):
        self.default_ttl = default_ttl
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.replace("/", "_").replace(" ", "_")
        return os.path.join(CACHE_DIR, safe + ".json")

    def set(self, key: str, value):
        try:
            data = {"value": value, "ts": time.time()}
            with open(self._path(key), "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Cache set error [{key}]: {e}")

    def get(self, key: str, ttl: int = None):
        ttl = ttl or self.default_ttl
        try:
            path = self._path(key)
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                data = json.load(f)
            age = time.time() - data.get("ts", 0)
            if age > ttl:
                return None
            return data.get("value")
        except Exception as e:
            logger.warning(f"Cache get error [{key}]: {e}")
            return None

    def delete(self, key: str):
        try:
            path = self._path(key)
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Cache delete error [{key}]: {e}")

    def get_timestamp(self, key: str) -> str | None:
        try:
            path = self._path(key)
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                data = json.load(f)
            ts = data.get("ts")
            if ts:
                import datetime
                return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        except Exception:
            return None

    def stats(self) -> dict:
        try:
            files = os.listdir(CACHE_DIR)
            return {"keys": [f.replace(".json", "") for f in files]}
        except Exception:
            return {"keys": []}
