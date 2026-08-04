from __future__ import annotations

import os

from cbok import settings


DEFAULT_BASE_REF = "origin/feature-zsv-5.1.0-encryption"


def _conf_get(section: str, option: str, default: str) -> str:
    conf = settings.CONF
    if conf.has_section(section) and conf.has_option(section, option):
        return conf.get(section, option).strip()
    return default


def zsv_base_ref() -> str:
    if settings.CONF.has_section("zsv") and settings.CONF.has_option("zsv", "base_ref"):
        return settings.CONF.get("zsv", "base_ref").strip()
    return _conf_get("zsv_compile", "base_ref", DEFAULT_BASE_REF)


def default_zstack_root() -> str:
    candidates = [
        os.path.join(settings.Workspace, "Cursor", "zs", "zstack"),
        os.path.join(settings.Workspace, "Cursor", "zs", "zstack-workspace", "zstack"),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[0]


def zstack_root_from_workspace() -> str:
    return os.path.realpath(default_zstack_root())
