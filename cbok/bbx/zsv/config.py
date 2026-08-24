from __future__ import annotations

import os

from cbok import settings


def zsv_base_ref() -> str:
    if settings.CONF.has_section("zsv") and settings.CONF.has_option("zsv", "base_ref"):
        return settings.CONF.get("zsv", "base_ref").strip()
    return ""


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
