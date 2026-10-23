from __future__ import annotations

from cbok import settings


def zsv_base_ref() -> str:
    if settings.CONF.has_section("zsv") and settings.CONF.has_option("zsv", "base_ref"):
        return settings.CONF.get("zsv", "base_ref").strip()
    return ""


def zsv_sync_repos() -> tuple[str, ...]:
    if not settings.CONF.has_section("zsv") or not settings.CONF.has_option("zsv", "sync_repos"):
        return ()
    return tuple(
        repo.strip()
        for repo in settings.CONF.get("zsv", "sync_repos").split(",")
        if repo.strip()
    )
