# Third-party notices and source provenance

This checkout originated from `dughogan/nuke_mcp` and is maintained in
`cedarconnor/nuke_mcp`. No repository-level LICENSE file was present in the inspected source
at this release qualification. This document does **not** grant or invent a project license.
Obtain the appropriate rights before redistributing material whose license is unspecified.
Existing upstream authorship and notices must be preserved.

The expansion was implemented against this repository's contracts. The compared Nuke/DCC MCP
repositories informed feature selection; no source code from those comparison repositories was
copied into Task 15. Their licenses do not become this project's license.

## External Python dependencies

The environment used for qualification reports installed distribution metadata as follows:

| Distribution | Installed version | Declared license | Source |
| --- | --- | --- | --- |
| FastMCP | 2.14.7 (pinned in requirements.txt) | Apache-2.0 | [FastMCP](https://github.com/jlowin/fastmcp) |
| MCP Python SDK | 1.29.0 (resolved transitive dependency) | MIT | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |

Both installed distributions include a `LICENSE` file in their distribution metadata.
This table is not a complete transitive dependency bill of materials; preserve the licenses
bundled with every dependency if redistributing an environment. The repository does not vendor
these dependencies. Install them into the external Python environment, not Nuke's Python.

Nuke and its bundled Qt/PySide components are supplied by Foundry and their respective owners.
They are not redistributed by this repository. The native tests require a separately installed,
appropriately licensed host. NC-generated scripts and toolsets use `.nknc`; support for their
workflow does not remove Foundry's license restrictions.
