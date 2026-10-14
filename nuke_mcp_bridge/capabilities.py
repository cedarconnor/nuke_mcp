"""Host facts only: no node creation, license secrets, or speculative probes."""

import os
from . import __version__


def probe_capabilities(nuke):
    env = getattr(nuke, "env", {})
    if env.get("studio", "unknown") is True:
        flavor = "nukestudio"
    elif env.get("nukex", "unknown") is True:
        flavor = "nukex"
    elif env.get("nukex", "unknown") is False or env.get("studio", "unknown") is False:
        flavor = "nuke"
    else:
        flavor = "unknown"
    nc = env.get("nc", "unknown")
    if nc == "unknown":
        nc = env.get("noncommercial", "unknown")
    license_mode = "noncommercial" if nc is True else "unknown"
    return {
        "protocol_version": 2, "addon_version": __version__, "pid": os.getpid(),
        "nuke_version": getattr(nuke, "NUKE_VERSION_STRING", env.get("NukeVersionString", "unknown")),
        "gui": getattr(nuke, "GUI", None), "host_flavor": flavor,
        "license_mode": license_mode,
        "graph_observation": "partial_or_unknown" if nc is True else "unknown",
        "node_class_discovery": "advisory",
        "tool_groups": ["legacy_core", "capabilities", "operation_status", "verified_edits", "batch_edit", "inspection"],
        "inspection_limits": {"nodes":1000, "knobs_per_node":128, "channels_per_read":2048,
                              "evaluated_paths":10000, "evidence_bytes":4*1024*1024},
        "unsupported_tool_groups": ["shot_manifests", "scene_events", "scene_revisions"],
        "edit_limits": {"batch_operations": 100, "static_knobs_only": True,
                        "legacy_compound_workflows": "unverified", "creation_scope": "root"},
    }
