"""Preserve legacy tool schemas and text while carrying real MCP error receipts."""

from contextvars import ContextVar
from functools import wraps
import inspect
from uuid import uuid4
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolResult

from .protocol import make_result, BridgeError

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
                failed = next((r for r in receipts if r["state"] in ("failed", "cancelled", "expired")), None)
                if failed is not None:
                    result = failed
                elif receipts:
                    result = receipts[-1]
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
