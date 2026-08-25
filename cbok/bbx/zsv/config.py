from __future__ import annotations

from cbok import settings


def zsv_base_ref() -> str:
    if settings.CONF.has_section("zsv") and settings.CONF.has_option("zsv", "base_ref"):
        return settings.CONF.get("zsv", "base_ref").strip()
    return ""
