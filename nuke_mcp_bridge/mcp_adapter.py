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
    @mcp.tool(output_schema=None, annotations={"readOnlyHint":True})
    def plan_layered_comp(manifest: dict) -> ToolResult:
        """Validate explicit source layers/channels, masks and Merge ordering without graph changes."""
        result=client().call('plan_layered_comp',dict(manifest=manifest))
        return to_mcp_result(result,'Layered comp plan: '+result['state'])

    @mcp.tool(output_schema=None)
    def build_layered_comp(manifest: dict, plan_digest: str) -> ToolResult:
        """Build a fresh planned Group. Preserve unrelated nodes; saving/rendering remain separate."""
        result=client().call('build_layered_comp',dict(manifest=manifest,plan_digest=plan_digest))
        return to_mcp_result(result,'Layered comp build: '+result['state'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint":True})
    def import_shot_csv(path: str, column_map: dict, defaults: dict) -> ToolResult:
        """Convert a host CSV using explicit header-to-field mapping and defaults; resolve returned validation errors."""
        result=client().call('import_shot_csv',dict(path=path,column_map=column_map,defaults=defaults))
        return to_mcp_result(result,'CSV conversion: '+result['state'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint":True})
    def plan_shot_setup(manifest: dict) -> ToolResult:
        """Validate schema-v1 shot paths, sources, host/settings and publication collisions without mutation."""
        result=client().call('plan_shot_setup',dict(manifest=manifest))
        return to_mcp_result(result,'Shot plan: '+result['state'])

    @mcp.tool(output_schema=None)
    def apply_shot_setup(manifest: dict, plan_digest: str) -> ToolResult:
        """Apply a fresh shot plan only in a clean, explicitly opted-in disposable GUI host. Never retry unknown outcomes."""
        result=client().call('apply_shot_setup',dict(manifest=manifest,plan_digest=plan_digest))
        return to_mcp_result(result,'Shot setup: '+result['state'])

    @mcp.tool(output_schema=None)
    def open_script(path: str, discard_unsaved_changes: bool = False) -> ToolResult:
        """Open an absolute trusted script path; refuse dirty work without explicit discard."""
        result=client().call('open_script',dict(path=path,discard_unsaved_changes=discard_unsaved_changes))
        return to_mcp_result(result,'Open script: '+result['state'])

    @mcp.tool(output_schema=None)
    def save_script(path: str | None = None, overwrite: bool = False) -> ToolResult:
        """Save current target, or save-as an absolute host-compatible path. Save-as refuses collisions by default."""
        result=client().call('save_script',dict(path=path,overwrite=overwrite))
        return to_mcp_result(result,'Save script: '+result['state'])

    @mcp.tool(output_schema=None)
    def set_project_settings(settings: dict, dry_run: bool = True) -> ToolResult:
        """Preflight/apply fps, first_frame, last_frame, format and exact color_management enums.

        Format requires width, height, pixel_aspect. Color management maps existing
        allowlisted knob names to exact observed enum labels. Apply is non-atomic.
        """
        result=client().call('set_project_settings',dict(settings=settings,dry_run=dry_run))
        return to_mcp_result(result,'Project settings: '+result['state'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def list_toolsets() -> ToolResult:
        """List digest-verified entries in the host's configured trusted library."""
        result=client().call('list_toolsets', {})
        return to_mcp_result(result, 'Toolset library: '+result['state'])

    @mcp.tool(output_schema=None)
    def save_toolset(node_paths: list[str], name: str, overwrite: bool = False) -> ToolResult:
        """Publish selected full paths as a verified library toolset; preserve selection."""
        result=client().call('save_toolset', dict(node_paths=node_paths,name=name,overwrite=overwrite))
        return to_mcp_result(result, 'Save toolset: '+result['state'])

    @mcp.tool(output_schema=None)
    def load_toolset(name: str, group_name: str, position: list[int] | None = None) -> ToolResult:
        """Execute a trusted library payload in a newly owned Group. Never retry unknown outcomes."""
        result=client().call('load_toolset', dict(name=name,group_name=group_name,position=position))
        return to_mcp_result(result, 'Load toolset: '+result['state'])

    @mcp.tool(output_schema=None, annotations={"readOnlyHint": True})
    def sample_channel_statistics(node_path: str, channels: list[str], frame: int,
                                  roi: list[int] | None = None, max_samples_per_channel: int = 1024) -> ToolResult:
        """Sample up to 16 channels with a filtered grid, at most 4096 samples each.

        ROI is [x,y,width,height]. Sampled extrema and zeros are not a full-image
        pixel audit. The original frame is restored; partial evidence survives failure.
        """
        result = client().call('sample_channel_statistics', dict(node_path=node_path, channels=channels,
                              frame=frame, roi=roi, max_samples_per_channel=max_samples_per_channel))
        return to_mcp_result(result, 'Filtered channel statistics: ' + result['state'])

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
