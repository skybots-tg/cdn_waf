"""
Edge Node Cache Purger

Handles fetching purge tasks from control plane,
executing cache purge on disk, and reporting results.
"""
import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Nginx cache key format used in our template: $scheme$host$request_uri
CACHE_KEY_FORMAT = "{scheme}{host}{uri}"

# Nginx levels=1:2 means: last 1 char of MD5 / next-to-last 2 chars / full MD5
CACHE_LEVELS = (1, 2)


def compute_cache_path(cache_dir: str, scheme: str, host: str, uri: str) -> Path:
    """
    Compute the on-disk path of a cached response given its cache key components.
    
    Nginx proxy_cache_path with levels=1:2 stores files as:
      <cache_dir>/<last_1_char>/<next_2_chars>/<full_md5>
    
    Example: MD5 = "b7f54b2df7773722d382f4809d650507"
      path = <cache_dir>/7/50/b7f54b2df7773722d382f4809d650507
    """
    key = CACHE_KEY_FORMAT.format(scheme=scheme, host=host, uri=uri)
    md5 = hashlib.md5(key.encode()).hexdigest()

    level1 = md5[-CACHE_LEVELS[0]:]             # last 1 char
    level2 = md5[-(CACHE_LEVELS[0] + CACHE_LEVELS[1]):-CACHE_LEVELS[0]]  # next 2 chars
    return Path(cache_dir) / level1 / level2 / md5


def _read_cache_file_key(filepath: Path) -> Optional[str]:
    """
    Read the KEY header from an Nginx cache file.
    Nginx writes a binary header followed by HTTP headers and the KEY line.
    The KEY is typically within the first 8KB of the file.
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(8192)
        
        text = header.decode("utf-8", errors="replace")
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("KEY:"):
                return stripped[4:].strip()
    except Exception:
        pass
    return None


class EdgeCachePurger:
    """Fetches purge tasks from control plane and executes them on disk."""

    def __init__(
        self,
        control_plane_url: str,
        node_id: int,
        api_key: str,
        cache_base_dir: str = "/var/cache/nginx",
        request_timeout: float = 15.0,
    ):
        self.control_plane_url = control_plane_url.rstrip("/")
        self.node_id = node_id
        self.api_key = api_key
        self.cache_base_dir = Path(cache_base_dir)
        self.request_timeout = request_timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Node-Id": str(self.node_id),
            "X-Node-Token": self.api_key,
        }

    def _safe_name(self, domain_name: str) -> str:
        return domain_name.replace(".", "_")

    def _cache_dir(self, domain_name: str) -> Path:
        return self.cache_base_dir / self._safe_name(domain_name)

    # ------------------------------------------------------------------
    # Networking: fetch tasks & report results
    # ------------------------------------------------------------------

    async def fetch_purge_tasks(self) -> List[Dict[str, Any]]:
        """Fetch pending purge tasks from control plane."""
        url = f"{self.control_plane_url}/internal/edge/purge-tasks"
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Failed to fetch purge tasks: %s", e)
            return []

    async def report_purge_complete(
        self, purge_id: int, success: bool = True
    ):
        """Report purge completion to control plane."""
        url = f"{self.control_plane_url}/internal/edge/purge-complete"
        payload = {"purge_id": purge_id, "success": success}
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.post(
                    url, json=payload, headers=self._headers()
                )
                response.raise_for_status()
                logger.info("Reported purge %s complete (success=%s)", purge_id, success)
        except Exception as e:
            logger.error("Failed to report purge %s: %s", purge_id, e)

    # ------------------------------------------------------------------
    # Purge execution
    # ------------------------------------------------------------------

    async def check_and_execute_purges(self):
        """Main entry point: fetch tasks, execute, report."""
        tasks = await self.fetch_purge_tasks()
        if not tasks:
            return

        logger.info("Received %d purge task(s)", len(tasks))

        for task in tasks:
            purge_id = task["purge_id"]
            domain_name = task["domain_name"]
            purge_type = task["purge_type"]
            targets = task.get("targets")

            try:
                if purge_type == "all":
                    deleted = self._purge_all(domain_name)
                elif purge_type == "url":
                    deleted = self._purge_by_urls(domain_name, targets or [])
                elif purge_type == "pattern":
                    patterns = targets or []
                    deleted = self._purge_by_patterns(domain_name, patterns)
                else:
                    logger.warning("Unknown purge type: %s", purge_type)
                    deleted = 0

                logger.info(
                    "Purge %s (%s) for %s: removed %d item(s)",
                    purge_id, purge_type, domain_name, deleted,
                )
                await self.report_purge_complete(purge_id, success=True)

            except Exception as e:
                logger.error("Purge %s failed: %s", purge_id, e, exc_info=True)
                await self.report_purge_complete(purge_id, success=False)

    # ------------------------------------------------------------------
    # Purge strategies
    # ------------------------------------------------------------------

    def _purge_all(self, domain_name: str) -> int:
        """Remove all cached files for a domain and recreate the directory."""
        cache_dir = self._cache_dir(domain_name)
        if not cache_dir.exists():
            logger.debug("Cache dir does not exist: %s", cache_dir)
            return 0

        count = sum(1 for _ in cache_dir.rglob("*") if _.is_file())
        shutil.rmtree(cache_dir)
        self._ensure_cache_dir(cache_dir)
        return count

    def _purge_by_urls(self, domain_name: str, urls: List[str]) -> int:
        """
        Remove cached files for specific URLs.
        
        Each URL should be a path like "/static/style.css".
        We try both http and https schemes.
        """
        cache_dir = self._cache_dir(domain_name)
        if not cache_dir.exists():
            return 0

        deleted = 0
        for url in urls:
            uri = url if url.startswith("/") else f"/{url}"
            for scheme in ("http://", "https://"):
                path = compute_cache_path(
                    str(cache_dir), scheme, domain_name, uri
                )
                if path.exists():
                    try:
                        path.unlink()
                        deleted += 1
                        logger.debug("Deleted cache file: %s", path)
                    except OSError as e:
                        logger.warning("Failed to delete %s: %s", path, e)

        return deleted

    def _purge_by_patterns(self, domain_name: str, patterns: List[str]) -> int:
        """
        Remove cached files matching glob/regex patterns by scanning cache directory.
        
        Reads the KEY header from each Nginx cache file and matches the URI
        portion against the provided patterns. Supports glob-style patterns
        (e.g. "*.jpg", "/static/*") which are converted to regex.
        """
        cache_dir = self._cache_dir(domain_name)
        if not cache_dir.exists():
            return 0

        compiled = []
        for pat in patterns:
            regex_pat = self._glob_to_regex(pat)
            try:
                compiled.append(re.compile(regex_pat))
            except re.error:
                logger.warning("Invalid pattern, skipping: %s", pat)

        if not compiled:
            return 0

        deleted = 0
        for filepath in cache_dir.rglob("*"):
            if not filepath.is_file():
                continue

            key = _read_cache_file_key(filepath)
            if not key:
                continue

            # Extract URI from cache key (format: scheme + host + uri)
            uri = self._extract_uri_from_key(key, domain_name)
            if not uri:
                continue

            if any(rx.search(uri) for rx in compiled):
                try:
                    filepath.unlink()
                    deleted += 1
                    logger.debug("Pattern-deleted cache file: %s (key=%s)", filepath, key)
                except OSError as e:
                    logger.warning("Failed to delete %s: %s", filepath, e)

        return deleted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_cache_dir(self, cache_dir: Path):
        """Recreate cache directory with proper ownership."""
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                import pwd
                import grp
                try:
                    uid = pwd.getpwnam("www-data").pw_uid
                    gid = grp.getgrnam("www-data").gr_gid
                except KeyError:
                    uid = pwd.getpwnam("nginx").pw_uid
                    gid = grp.getgrnam("nginx").gr_gid
                os.chown(str(cache_dir), uid, gid)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to recreate cache dir %s: %s", cache_dir, e)

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        """Convert a simple glob pattern to regex. Supports * and ?."""
        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\*", ".*")
        escaped = escaped.replace(r"\?", ".")
        return f"^{escaped}$"

    @staticmethod
    def _extract_uri_from_key(key: str, domain_name: str) -> Optional[str]:
        """
        Extract the URI part from a cache key.
        Key format: "http://example.com/path" or "https://example.com/path"
        """
        for scheme in ("https://", "http://"):
            prefix = f"{scheme}{domain_name}"
            if key.startswith(prefix):
                return key[len(prefix):]
        return None
