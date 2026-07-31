"""Add the patched Nuke MCP repository to Nuke's plug-in path."""

import os

import nuke


NUKE_MCP_REPO = os.environ.get("NUKE_MCP_REPO", r"D:/nuke_mcp")

if os.path.isdir(NUKE_MCP_REPO):
    nuke.pluginAddPath(NUKE_MCP_REPO)
else:
    nuke.warning(
        "Nuke MCP repository was not found at: {0}".format(NUKE_MCP_REPO)
    )
