"""Load the Nuke MCP panel after Nuke's graphical interface is available."""

try:
    import nuke_mcp_bridge
except ImportError as exc:
    raise ImportError(
        "Nuke MCP v2 requires the complete repository, including nuke_mcp_bridge/. "
        "Set NUKE_MCP_REPO to that directory; copying only the addon is insufficient."
    ) from exc

import nuke_mcp_addon
