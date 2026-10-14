"""Preserve legacy tool schemas and text while carrying real MCP error receipts."""

from contextvars import ContextVar
from functools import wraps
import inspect
from uuid import uuid4
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolResult

from .protocol import make_result, BridgeError
from .operations import READ_ONLY

_receipts = ContextVar("nuke_bridge_receipts", default=None)


def capture_receipt(result):
    current = _receipts.get()
    if current is not None:
        current.append(result)


class BridgeToolResult(ToolResult):
    def to_mcp_result(self):
        value = self.structured_content
        return CallToolResult(
            content=self.content, structuredContent=value,
            isError=value["state"] in ("failed", "cancelled", "expired"),
        )


def to_mcp_result(result, legacy_text):
    return BridgeToolResult(content=legacy_text, structured_content=result)


def combine_receipts(receipts):
    """Preserve every operation; an optional read cannot erase a later edit."""
    result = dict(receipts[-1])
    if len(receipts) == 1:
        return result
    result['operation_receipts'] = receipts
    result['source'] = 'mcp_aggregate'
    failed = [r for r in receipts if r['state'] in ('failed', 'cancelled', 'expired')]
    mutations = [r for r in receipts if r.get('command') not in READ_ONLY]
    required_failures = [r for r in failed if r.get('command') not in READ_ONLY or r is receipts[-1]]
    result['warnings'] = list(result['warnings']) + [
        'Earlier read failed: ' + str(r['error']) for r in failed if r not in required_failures]
    if required_failures:
        result.update(ok=False, state='failed', error=required_failures[-1]['error'])
        if any(r['outcome'] == 'unknown' for r in mutations):
            result['outcome'] = 'unknown'
        elif any(r['outcome'] in ('applied', 'partial') for r in mutations):
            result['outcome'] = 'partial'
        else:
            result['outcome'] = 'not_started'
    elif mutations:
        # Even a later successful read must not hide an earlier write outcome.
        result['outcome'] = mutations[-1]['outcome']
    return result


def bridge_tool(mcp):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            receipts = []
            token = _receipts.set(receipts)
            try:
                try:
                    text = fn(*args, **kwargs)
                except Exception as exc:
                    text = "Error: " + str(exc)
                if receipts:
                    result = combine_receipts(receipts)
                else:
                    result = make_result(dict(request_id=str(uuid4()), client_session_id=None,
                                              server_instance_id=None))
                    result["source"] = "mcp_validation"
                if str(text).lower().startswith(("error", "failed", "code execution failed", "invalid")):
                    if result["state"] not in ("failed", "cancelled", "expired"):
                        result = dict(result, ok=False, state="failed",
                                      error={"code": "tool_error", "message": str(text)},
                                      outcome="unknown" if receipts else "not_started")
                result = dict(result, tool=fn.__name__)
                return to_mcp_result(result, text)
            finally:
                _receipts.reset(token)
        wrapped.__signature__ = inspect.signature(fn).replace(return_annotation=ToolResult)
        wrapped.__annotations__ = dict(fn.__annotations__)
        wrapped.__annotations__["return"] = ToolResult
        return mcp.tool(output_schema=None)(wrapped)
    return decorate


def register_tools(mcp, client):
    """client is a callable returning the shared, lazily connected BridgeClient."""
    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def inspect_graph(max_nodes: int = 256, max_knobs_per_node: int = 64,
                      recurse_groups: bool = True, selected_only: bool = False) -> ToolResult:
        """Observe full-path graph connections and bounded knob snapshots. Check coverage and omissions."""
        result = client().call('inspect_graph', dict(max_nodes=max_nodes, max_knobs_per_node=max_knobs_per_node,
                              recurse_groups=recurse_groups, selected_only=selected_only))
        return to_mcp_result(result, 'Graph inspection: ' + result['observation']['coverage'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def inspect_reads(node_paths: list[str] | None = None, channel_limit: int = 256) -> ToolResult:
        """Observe Read/DeepRead files, channels, multipart choices and unavailable fields."""
        result = client().call('inspect_reads', dict(node_paths=node_paths, channel_limit=channel_limit))
        return to_mcp_result(result, 'Read inspection: ' + result['observation']['coverage'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def validate_reads(first_frame: int, last_frame: int, step: int = 1,
                       node_paths: list[str] | None = None) -> ToolResult:
        """Check up to 10000 frame/view paths. Unknown expressions are separate from missing files; no relinking."""
        result = client().call('validate_reads', dict(first_frame=first_frame, last_frame=last_frame,
                                                     step=step, node_paths=node_paths))
        return to_mcp_result(result, 'Read validation: ' + result['state'])

    @mcp.tool(output_schema=None)
    def batch_edit(operations: list[dict], dry_run: bool = True, expected_revision: int | None = None) -> ToolResult:
        """Preflight 1..100 set_knob/connect/position operations. Dry-run by default.

        Each item has op and node_path. set_knob adds knob/value; connect adds
        input_index/source_path (null disconnects); position adds x/y.
        Expected scene revisions are unavailable until a revision provider exists.
        Apply is non-atomic: earlier successful edits remain after a failure.
        """
        result = client().call('batch_edit', dict(operations=operations, dry_run=dry_run,
                                                expected_revision=expected_revision))
        return to_mcp_result(result, 'Batch ' + result['state'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def get_capabilities() -> ToolResult:
        """Report current host identity and observable capabilities."""
        result = client().call("get_capabilities", {})
        return to_mcp_result(result, "Nuke capabilities" if result["ok"] else str(result["error"]))

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def get_operation_status(request_id: str, server_instance_id: str) -> ToolResult:
        """Read a retained receipt. Unknown/expired receipts never authorize mutation replay."""
        result = client().status(request_id, server_instance_id)
        return to_mcp_result(result, "Operation " + result["state"])

    @mcp.tool(output_schema=None)
    def cancel_operation(request_id: str, server_instance_id: str) -> ToolResult:
        """Cancel queued work, or request cancellation between native render frames."""
        result = client().cancel(request_id, server_instance_id)
        return to_mcp_result(result, "Operation " + result["state"])

    @mcp.tool(output_schema=None)
    def start_render(write_node: str, first_frame: int, last_frame: int, step: int = 1) -> ToolResult:
        """Queue a render and return its request/instance IDs for status polling."""
        result = client().submit("render", dict(write_node=write_node, first_frame=first_frame,
                                               last_frame=last_frame, step=step))
        return to_mcp_result(result, "Render " + result["state"] + "; query get_operation_status")
