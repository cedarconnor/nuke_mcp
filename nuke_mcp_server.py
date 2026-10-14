from fastmcp import FastMCP, Context
from nuke_mcp_bridge.mcp_adapter import bridge_tool, capture_receipt, register_tools
import socket
import json
import asyncio
import logging
import time
import os
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("NukeMCPServer")
DEFAULT_NUKE_PORT = int(os.environ.get("NUKE_MCP_PORT", "9877"))

# Workflow Rules for Nuke Compositing - with stability focus
class NukeWorkflowRules:
    """Enforce professional compositing workflow rules for Nuke operations with stability focus."""
    
    @staticmethod
    def get_valid_node_types():
        """Get list of valid Nuke node types to prevent crashes."""
        # Standard Nuke node types that should always be available
        # Using the reference list from the guidelines
        return [
            # Input/Output
            "Read", "Write", "Viewer",
            # Color
            "Grade", "ColorCorrect", "Saturation", "HueCorrect", "ColorLookup",
            # Channel
            "Shuffle", "ShuffleCopy", "Copy",
            # Filter
            "Blur", "Defocus", "Sharpen", "Median", "EdgeBlur",
            # Keyer
            "Keyer", "Primatte", "IBKColour", "IBKGizmo", "Keylight",
            # Merge
            "Merge2", "Premult", "Unpremult", "Screen", "Plus",
            # Transform
            "Transform", "Reformat", "Crop", "CornerPin2D",
            # 3D
            "Scene", "Camera", "Light", "Axis", "Card", "Cube", "Sphere", "ScanlineRender",
            # Deep
            "DeepMerge", "DeepRecolor",
            # Misc
            "Dot", "Switch", "TimeOffset", "NoOp", "Text", "Roto", "RotoPaint",
            # Special nodes with different creation patterns
            "BackdropNode"
        ]
        
    @staticmethod       
    def validate_node_creation(node_type, name=None, parameters=None):
        """Validate node creation against workflow rules."""
        issues = []
        valid_node_types = NukeWorkflowRules.get_valid_node_types()
        
        # 1. Node type validation - critical for stability
        if node_type not in valid_node_types:
            # Simple validation without suggestions to keep this light
            issues.append(f"Invalid node type: {node_type}")
            
        # 2. Node Labeling Conventions - Never rename, always use labels
        if name:
            # Instead of suggesting name changes, always suggest using labels
            issues.append(f"Consider using the default node naming and adding descriptive labels instead of custom node names")
        
        # 3. Add automatic labels based on node type if not present
        if parameters is None:
            parameters = {}
            
        # Handle specific node types with special labeling
        if node_type == "Write" and "label" not in parameters:
            output_name = os.path.basename(parameters.get("file", "output"))
            parameters["label"] = f"OUT: {output_name}"
            
        if node_type == "Read" and "label" not in parameters:
            source_name = os.path.basename(parameters.get("file", "source"))
            parameters["label"] = f"IN: {source_name}"
            
        if node_type in ["Grade", "ColorCorrect"] and "label" not in parameters:
            parameters["label"] = "COLOR"
            
        if node_type in ["Transform", "Tracker"] and "label" not in parameters:
            parameters["label"] = "XFORM"
            
        if node_type in ["Blur", "Defocus", "ZDefocus"] and "label" not in parameters:
            parameters["label"] = "FX"
            
        if node_type in ["Keyer", "Primatte", "IBKColour"] and "label" not in parameters:
            parameters["label"] = "KEY"
        
        # 4. Required Parameters Check (stability critical)
        if node_type == "Read" and parameters:
            if "file" not in parameters:
                issues.append("Read nodes should specify a 'file' parameter")
        
        # Add a default file path parameter to prevent empty Read nodes
        if node_type == "Read" and "file" not in parameters:
            parameters["file"] = ""  # Empty but present
        
        if node_type == "Write" and parameters:
            if "file" not in parameters:
                issues.append("Write nodes should specify a 'file' parameter")
                parameters["file"] = ""  # Empty but present
                
            # Ensure create_directories is enabled for stability
            parameters["create_directories"] = True
        
        # 5. Color-related Node Rules
        color_correction_nodes = ["Grade", "ColorCorrect", "HueCorrect", "Saturation"]
        if node_type in color_correction_nodes:
            # Suggest unpremult before color correction
            issues.append("Consider adding Unpremult before color correction and Premult after")
        
        return issues, parameters
    
    @staticmethod
    def validate_node_modification(name, node_type="unknown", parameters=None, position=None):
        """Validate node modification against workflow rules."""
        issues = []
        
        # 1. Don't rename nodes, use label instead
        if parameters and "name" in parameters:
            issues.append("Avoid renaming nodes. Use 'label' knob to add descriptive text instead.")
            
            # Convert name change to label change for stability
            if "label" not in parameters:
                parameters["label"] = f"({parameters['name']})"
            else:
                parameters["label"] += f" ({parameters['name']})"
            # Remove the name parameter
            del parameters["name"]
        
        # 2. Write Node Settings
        if (name and (name.startswith("Write") or name.startswith("OUT_")) or node_type == "Write") and parameters:
            parameters["create_directories"] = True
        
        # 3. Validate parameters based on node type
        if node_type != "unknown":
            # Only handle parameters that exist on this node type
            # This is a simplification - a comprehensive solution would check against known knobs for each node type
            pass
        
        return issues, parameters
    
    @staticmethod
    def validate_node_connection(output_node, input_node, input_index=0):
        """Validate node connections against workflow rules."""
        issues = []
        
        # 1. B-pipe Structure
        if input_index == 0 and "Merge" in input_node:
            issues.append("For Merge nodes, connect main pipeline to input B (1) to maintain B-pipe structure.")
            # Auto-fix the input index
            input_index = 1
            
        return issues, input_index
    
    @staticmethod
    def validate_node_position(node_name, new_position):
        """Validate node positioning against workflow rules."""
        issues = []
        
        # Check for diagonal positioning which is discouraged
        if hasattr(NukeWorkflowRules, 'last_position'):
            last_x, last_y = NukeWorkflowRules.last_position
            new_x, new_y = new_position
            
            if last_x != new_x and last_y != new_y:
                issues.append("Diagonal node positioning detected. Consider vertical stacking for cleaner graphs.")
                # Suggest a clean vertical position
                new_position = [last_x, new_y]
        
        # Store position for next check
        NukeWorkflowRules.last_position = new_position
        
        return issues, new_position
    
    @staticmethod
    def get_node_type_suggestions(node_type):
        """Get workflow suggestions for specific node types."""
        suggestions = {
            "Merge2": [
                "Use Merge nodes with 'over' operation for standard compositing",
                "Connect main pipeline to input B (1) for consistent B-pipe structure",
                "For operations like 'plus' or 'screen', consider using the appropriate operation"
            ],
            "Grade": [
                "Consider using Unpremult before and Premult after for premultiplied images",
                "Use white.a as mask to only affect specific areas",
                "Keep color corrections subtle and use multiple Grade nodes for different adjustments"
            ],
            "ColorCorrect": [
                "Split adjustments between shadows, midtones, and highlights",
                "Consider using Unpremult before and Premult after for premultiplied images"
            ],
            "Blur": [
                "Be specific about which channels to blur",
                "Consider using separate blur values for rgb and alpha when appropriate",
                "Use smaller blur sizes when possible for performance"
            ],
            "Transform": [
                "Use center controls to define rotation point",
                "Enable motion blur when animating transforms",
                "Consider 'black outside' vs 'format' settings based on needs"
            ],
            "Roto": [
                "Name shapes descriptively within the node",
                "Use motion blur when needed for moving objects",
                "Use feather instead of blur nodes when possible for shape edges"
            ],
            "Keyer": [
                "Despill after keying, not before",
                "Use core matte and edge adjustments in separate nodes",
                "Consider unpremultiplication when color correcting keyed elements"
            ]
        }
        
        return suggestions.get(node_type, [])
    
    @staticmethod
    def apply_auto_fixes(node_type, parameters=None):
        """Apply automatic fixes to parameters based on best practices."""
        fixed_parameters = parameters.copy() if parameters else {}
        
        # Auto-fix common issues
        if node_type == "Write":
            fixed_parameters["create_directories"] = True
        
        if node_type in ["Grade", "ColorCorrect", "HueCorrect"]:
            # Add default mask channel if not specified
            if "maskChannelInput" not in fixed_parameters:
                fixed_parameters["maskChannelInput"] = "none"
        
        if node_type == "Merge2":
            # Set default operation to over if not specified
            if "operation" not in fixed_parameters:
                fixed_parameters["operation"] = "over"
            # Set bbox handling to union if not specified
            if "bbox" not in fixed_parameters:
                fixed_parameters["bbox"] = "union"
                
        if node_type == "Blur":
            # Only blur RGB by default, not alpha
            if "channels" not in fixed_parameters:
                fixed_parameters["channels"] = "rgb"
                
        return fixed_parameters
    
    @staticmethod
    def get_workflow_template(template_type):
        """Get a workflow template definition for common compositing tasks."""
        templates = {
            "keying": [
                {"type": "Keyer", "name": "Keyer1", "label": "KEY: Primary"},
                {"type": "Unpremult", "name": "Unpremult1", "label": "PREP: Unpremult"},
                {"type": "Grade", "name": "Despill", "label": "COLOR: Despill", "parameters": {"label": "Despill"}},
                {"type": "Premult", "name": "Premult1", "label": "PREP: Premult"},
                {"type": "EdgeBlur", "name": "EdgeBlur1", "label": "FX: Edge Refinement", "parameters": {"size": 2}}
            ],
            "color_correction": [
                {"type": "Unpremult", "name": "Unpremult1", "label": "PREP: Unpremult"},
                {"type": "Grade", "name": "Grade1", "label": "COLOR: Overall", "parameters": {"label": "Overall"}},
                {"type": "Grade", "name": "GradeShadows", "label": "COLOR: Shadows", "parameters": {"label": "Shadows"}},
                {"type": "Grade", "name": "GradeHighlights", "label": "COLOR: Highlights", "parameters": {"label": "Highlights"}},
                {"type": "Premult", "name": "Premult1", "label": "PREP: Premult"}
            ],
            "lens_distortion": [
                {"type": "LensDistortion", "name": "Undistort", "label": "LENS: Undistort", "parameters": {"label": "Undistort"}},
                {"type": "NoOp", "name": "ProcessingMiddle", "label": "MIDDLE: Processing Area"},
                {"type": "LensDistortion", "name": "Redistort", "label": "LENS: Redistort", "parameters": {"label": "Redistort", "direction": "distort"}}
            ],
            "3d_simple": [
                {"type": "Camera", "name": "Camera1", "label": "3D: Camera"},
                {"type": "Card", "name": "Card1", "label": "3D: Card"},
                {"type": "Scene", "name": "Scene1", "label": "3D: Scene"},
                {"type": "ScanlineRender", "name": "ScanlineRender1", "label": "3D: Render"}
            ]
        }
        
        return templates.get(template_type, [])
    
    @staticmethod
    def suggest_backdrop_organization():
        """Suggest backdrop organization for node graph clarity."""
        return [
            {"name": "INPUTS", "color": "0x7171C6FF"},  # Blue
            {"name": "PREP", "color": "0x9292E1FF"},    # Light Blue
            {"name": "KEY", "color": "0x8A8A5BFF"},     # Olive
            {"name": "COLOR", "color": "0xC67171FF"},   # Red 
            {"name": "FX", "color": "0x71C691FF"},      # Green
            {"name": "OUTPUT", "color": "0xDFDF36FF"}   # Yellow
        ]

class NukeConnection:
    """Compatibility facade over the correlated v2 client."""
    def __init__(self, host, port):
        from nuke_mcp_bridge.client import BridgeClient
        self.client = BridgeClient(host, port)

    def disconnect(self):
        self.client.close()

    def send_command(self, command_type, params=None):
        result = self.client.call(command_type, params or {})
        capture_receipt(dict(result, command=command_type))
        if not result["ok"]:
            from nuke_mcp_bridge.protocol import BridgeError
            error = result.get("error") or {}
            raise BridgeError(error.get("code", "host_error"), error.get("message", "Host failed"),
                              result["outcome"], result)
        return result["data"]


_nuke_connection = None
_connection_lock = __import__("threading").Lock()


def get_nuke_connection():
    global _nuke_connection
    with _connection_lock:
        if _nuke_connection is None:
            _nuke_connection = NukeConnection(host="localhost", port=DEFAULT_NUKE_PORT)
        return _nuke_connection

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        # Log that we're starting up
        logger.info("NukeMCP server starting up")
        logger.info("This server will connect to Nuke when a client makes a request")
        logger.info("Make sure Nuke is running with the addon active (NukeMCP panel with 'Running' status)")
        
        # We don't try to connect to Nuke on startup anymore
        # Instead, we'll connect when the first request comes in
        
        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _nuke_connection
        if _nuke_connection:
            logger.info("Disconnecting from Nuke on shutdown")
            _nuke_connection.disconnect()
            _nuke_connection = None
        logger.info("NukeMCP server shut down")

# Create the MCP server
mcp = FastMCP("NukeMCP", lifespan=server_lifespan)
register_tools(mcp, lambda: get_nuke_connection().client)

@bridge_tool(mcp)
def get_script_info(ctx: Context) -> str:
    """Get detailed information about the current Nuke script"""
    try:
        logger.info("Tool called: get_script_info")
        nuke = get_nuke_connection()
        result = nuke.send_command("get_script_info")
        
        # Format the response in a more human-readable way
        script_name = result.get("name", "Untitled")
        fps = result.get("fps", 0)
        format_info = result.get("format", "Unknown")
        first_frame = result.get("first_frame", 0)
        last_frame = result.get("last_frame", 0)
        nodes = result.get("nodes", [])
        
        # Create a summary of the script
        output = f"Script: {script_name}\n"
        output += f"Frame Range: {first_frame} - {last_frame} @ {fps} fps\n"
        output += f"Format: {format_info}\n\n"
        
        # Count node types
        node_types = {}
        for node in nodes:
            node_type = node.get("type", "Unknown")
            if node_type in node_types:
                node_types[node_type] += 1
            else:
                node_types[node_type] = 1
        
        output += f"Total Nodes: {len(nodes)}\n"
        output += "Node Types:\n"
        for node_type, count in sorted(node_types.items()):
            output += f"  - {node_type}: {count}\n"
        
        return output
    except Exception as e:
        logger.error(f"Error in get_script_info: {str(e)}")
        return f"Error getting script info: {str(e)}"

@bridge_tool(mcp)
def get_node_info(ctx: Context, node_name: str) -> str:
    """
    Get detailed information about a specific node in the Nuke script.
    
    Parameters:
    - node_name: The name of the node to get information about
    """
    try:
        logger.info(f"Tool called: get_node_info for node {node_name}")
        nuke = get_nuke_connection()
        result = nuke.send_command("get_node_info", {"name": node_name})
        
        # Format the response in a more human-readable way
        node_type = result.get("type", "Unknown")
        position = result.get("position", [0, 0])
        inputs = result.get("inputs", [])
        parameters = result.get("parameters", {})
        
        output = f"Node: {node_name} ({node_type})\n"
        output += f"Position: X={position[0]}, Y={position[1]}\n\n"
        
        # Show inputs
        output += "Inputs:\n"
        if inputs:
            for i, input_info in enumerate(inputs):
                if input_info:
                    output += f"  {i}: {input_info.get('name')} ({input_info.get('type')})\n"
                else:
                    output += f"  {i}: None\n"
        else:
            output += "  None\n"
        
        # Show parameters
        output += "\nParameters:\n"
        if parameters:
            for name, param in sorted(parameters.items()):
                value = param.get("value", "")
                if isinstance(value, list):
                    value_str = ", ".join(str(v) for v in value)
                    output += f"  {name}: [{value_str}]\n"
                else:
                    output += f"  {name}: {value}\n"
        else:
            output += "  No visible parameters\n"
        
        # Add workflow suggestions for this node type
        suggestions = NukeWorkflowRules.get_node_type_suggestions(node_type)
        if suggestions:
            output += "\nBest practices for this node type:\n"
            for suggestion in suggestions:
                output += f"  - {suggestion}\n"
        
        return output
    except Exception as e:
        logger.error(f"Error in get_node_info: {str(e)}")
        return f"Error getting node info: {str(e)}"

@bridge_tool(mcp)
def create_node(ctx: Context, node_type: str, name: str = None,
                position: List[int] = None, inputs: List[str] = None,
                parameters: Dict[str, Any] = None) -> str:
    """Create a node with explicit inputs and verified readback; no uncertain replay."""
    try:
        result = get_nuke_connection().send_command('create_node', {
            'node_type': node_type, 'name': name, 'position': position,
            'inputs': inputs, 'parameters': parameters})
        return "Created {0} node named '{1}'".format(result['type'], result['path'])
    except Exception as exc:
        return 'Error creating node: ' + str(exc)

@bridge_tool(mcp)
def modify_node(ctx: Context, name: str, parameters: Dict[str, Any] = None,
                position: List[int] = None, inputs: List[str] = None) -> str:
    """Preflight every requested edit, then apply with per-item readback results."""
    try:
        result = get_nuke_connection().send_command('modify_node', {
            'name': name, 'parameters': parameters, 'position': position, 'inputs': inputs})
        return "Modified node '{0}' - {1} verified edit(s)".format(result.get('path', name), len(result.get('items', [])))
    except Exception as exc:
        return 'Error modifying node: ' + str(exc)

@bridge_tool(mcp)
def delete_node(ctx: Context, name: str) -> str:
    """
    Delete a node from the Nuke script.
    
    Parameters:
    - name: Name of the node to delete
    """
    try:
        logger.info(f"Tool called: delete_node for node {name}")
        nuke = get_nuke_connection()
        result = nuke.send_command("delete_node", {"name": name})
        
        deleted_name = result.get("deleted", name)
        node_type = result.get("type", "unknown")
        return f"Deleted {node_type} node '{deleted_name}'"
    except Exception as e:
        logger.error(f"Error in delete_node: {str(e)}")
        return f"Error deleting node: {str(e)}"

@bridge_tool(mcp)
def position_node(ctx: Context, name: str, x: int, y: int) -> str:
    """Set a node's exact position and verify readback."""
    try:
        result = get_nuke_connection().send_command('position_node', {'name': name, 'position': [x, y]})
        return "Positioned node '{0}' at {1}".format(result['path'], result['position'])
    except Exception as exc:
        return 'Error positioning node: ' + str(exc)

@bridge_tool(mcp)
def connect_nodes(ctx: Context, output_node: str, input_node: str, input_index: int = 0) -> str:
    """Connect explicit node paths at the requested input and verify readback."""
    try:
        result = get_nuke_connection().send_command('connect_nodes', {
            'output_node': output_node, 'input_node': input_node, 'input_index': input_index})
        return "Connected {0} to {1} input {2}".format(result['output_node'], result['input_node'], input_index)
    except Exception as exc:
        return 'Error connecting nodes: ' + str(exc)

@bridge_tool(mcp)
def render(
    ctx: Context,
    frame_range: str = None,
    write_node: str = None,
    proxy_mode: bool = False
) -> str:
    """
    Render frames from the Nuke script.
    
    Parameters:
    - frame_range: Range of frames to render (e.g., "1-10" or "1,3,5-10")
    - write_node: Optional name of Write node to render (if None, renders all)
    - proxy_mode: Whether to render in proxy mode
    """
    try:
        logger.info(f"Tool called: render with range {frame_range}, write_node: {write_node}")
        nuke = get_nuke_connection()
        result = nuke.send_command("render", {
            "frame_range": frame_range,
            "write_node": write_node,
            "proxy_mode": proxy_mode
        })
        
        status = result.get("status", "Rendering completed")
        return f"{status}"
    except Exception as e:
        logger.error(f"Error in render: {str(e)}")
        return f"Error initiating render: {str(e)}"

@bridge_tool(mcp)
def viewer_playback(
    ctx: Context,
    action: str = "play",
    start_frame: int = None,
    end_frame: int = None
) -> str:
    """
    Control Nuke's Viewer playback.
    
    Parameters:
    - action: Playback action (play, stop, next, prev)
    - start_frame: Optional starting frame for playback
    - end_frame: Optional ending frame for playback
    """
    try:
        logger.info(f"Tool called: viewer_playback with action {action}")
        nuke = get_nuke_connection()
        result = nuke.send_command("viewer_playback", {
            "action": action,
            "start_frame": start_frame,
            "end_frame": end_frame
        })
        
        status = result.get("status", "Viewer operation completed")
        return status
    except Exception as e:
        logger.error(f"Error in viewer_playback: {str(e)}")
        return f"Error controlling viewer: {str(e)}"

@bridge_tool(mcp)
def execute_nuke_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Nuke.
    
    Parameters:
    - code: The Python code to execute
    """
    try:
        logger.info(f"Tool called: execute_nuke_code with code length {len(code)}")
        
        # Basic validation of code
        dangerous_patterns = [
            "shutil.rmtree", "os.rmdir", "os.remove",  # File deletion
            "sys.exit", "os._exit", "quit",  # Program termination
            "subprocess.call", "subprocess.Popen", "os.system",  # Command execution
        ]
        
        for pattern in dangerous_patterns:
            if pattern in code:
                warning_msg = f"Warning: Code contains potentially unsafe operation: {pattern}"
                logger.warning(warning_msg)
                # Continue execution but log the warning
        
        nuke = get_nuke_connection()
        result = nuke.send_command("execute_code", {"code": code})
        
        if result.get("executed", False):
            output = result.get("output", {})
            if output:
                # Format any output from the executed code
                output_str = "\n".join(f"{k}: {v}" for k, v in output.items())
                return f"Code executed successfully with output:\n{output_str}"
            else:
                return "Code executed successfully"
        else:
            error = result.get("error", "Unknown error")
            return f"Code execution failed: {error}"
    except Exception as e:
        logger.error(f"Error in execute_nuke_code: {str(e)}")
        return f"Error executing code: {str(e)}"

@bridge_tool(mcp)
def auto_layout_nodes(ctx: Context, selected_only: bool = False) -> str:
    """
    Automatically arrange nodes in the Nuke script for better readability.
    
    Parameters:
    - selected_only: Only arrange currently selected nodes if True
    """
    try:
        logger.info(f"Tool called: auto_layout_nodes with selected_only={selected_only}")
        nuke = get_nuke_connection()
        
        # Use the improved auto_layout implementation with better error handling
        # We send the code directly for execution to avoid the "expecting a Nuke node type" error
        auto_layout_code = f"""
import nuke

def auto_layout_nodes(selected_only={selected_only}):
    # Automatically arrange nodes in the script
    try:
        if selected_only:
            # Get selected nodes
            nodes = [n for n in nuke.allNodes() if n.isSelected()]
            if not nodes:
                return "No nodes selected"
        else:
            # Get all nodes
            nodes = nuke.allNodes()
        
        # Use Nuke's auto placement function for individual nodes
        for node in nodes:
            try:
                # Call autoplace on each individual node
                nuke.autoplace(node)
            except Exception as e:
                print(f"Warning: could not auto-place node {{node.name()}}: {{str(e)}}")
        
        return f"Auto-arranged {{len(nodes)}} nodes"
    except Exception as e:
        return f"Auto layout error: {{str(e)}}"

# Execute the function
result = auto_layout_nodes()
output = {{"status": result}}
"""
        
        result = nuke.send_command("legacy_workflow", {"code": auto_layout_code})
        
        if result.get("executed", False):
            output = result.get("output", {})
            status = output.get("status", "Nodes arranged")
            return status
        else:
            error = result.get("error", "Unknown error")
            return f"Failed to auto-layout nodes: {error}"
    except Exception as e:
        logger.error(f"Error in auto_layout_nodes: {str(e)}")
        return f"Error arranging nodes: {str(e)}"

@bridge_tool(mcp)
def set_frames(
    ctx: Context,
    first_frame: int = None,
    last_frame: int = None,
    current_frame: int = None
) -> str:
    """
    Set the frame range and current frame in the Nuke script.
    
    Parameters:
    - first_frame: New value for first frame
    - last_frame: New value for last frame
    - current_frame: New value for current frame
    """
    try:
        logger.info(f"Tool called: set_frames")
        nuke = get_nuke_connection()
        result = nuke.send_command("set_frames", {
            "first_frame": first_frame,
            "last_frame": last_frame,
            "current_frame": current_frame
        })
        
        return f"Updated frame settings - First: {result['first_frame']}, Last: {result['last_frame']}, Current: {result['current_frame']}"
    except Exception as e:
        logger.error(f"Error in set_frames: {str(e)}")
        return f"Error setting frames: {str(e)}"

@bridge_tool(mcp)
def create_viewer(ctx: Context, input_node: str = None) -> str:
    """
    Create a Viewer node connected to the specified input node.
    
    Parameters:
    - input_node: Optional name of node to connect to the Viewer
    """
    try:
        logger.info(f"Tool called: create_viewer connected to {input_node}")
        nuke = get_nuke_connection()
        result = nuke.send_command("create_viewer", {
            "input_node": input_node
        })
        
        viewer_name = result.get("name", "Viewer")
        if input_node:
            return f"Created Viewer node '{viewer_name}' connected to '{input_node}'"
        else:
            return f"Created Viewer node '{viewer_name}'"
    except Exception as e:
        logger.error(f"Error in create_viewer: {str(e)}")
        return f"Error creating viewer: {str(e)}"

@bridge_tool(mcp)
def create_workflow_template(
    ctx: Context,
    template_type: str,
    root_position: List[int] = None,
    add_backdrop: bool = True
) -> str:
    """
    Create a template node structure for common compositing tasks with stability focus.
    
    Parameters:
    - template_type: Type of template to create (e.g., "keying", "color_correction", "lens_distortion", "3d_simple")
    - root_position: Base position for the template [x, y]
    - add_backdrop: Whether to add a backdrop node around the template
    """
    try:
        # Default position if none provided
        if root_position is None:
            root_position = [0, 0]
        
        # Get the template nodes
        template_nodes = NukeWorkflowRules.get_workflow_template(template_type)
        
        if not template_nodes:
            return f"No template found for '{template_type}'. Available templates: keying, color_correction, lens_distortion, 3d_simple"
        
        # Use the stable node creation pattern from the guidelines
        # First, create the code that will execute in Nuke
        create_template_code = f"""
import nuke

try:
    # Track created nodes
    nodes = {{}}
    
    # 1. Create all nodes first
    # SAFETY: Create all nodes first before attempting any connections
"""
        
        # Generate code to create each node
        x, y = root_position
        for i, node_info in enumerate(template_nodes):
            node_type = node_info.get("type")
            node_name = node_info.get("name", f"{node_type}_{i}")
            label = node_info.get("label", "")
            node_params = node_info.get("parameters", {})
            
            # Handle BackdropNode differently
            if node_type == "BackdropNode":
                create_template_code += f"""
    # Create Backdrop node
    nodes["{node_name}"] = nuke.nodes.BackdropNode(xpos={x}, ypos={y + (i * 80)})
"""
            else:
                # Regular node creation
                create_template_code += f"""
    # Create {node_type} node
    try:
        nodes["{node_name}"] = nuke.createNode("{node_type}", inpanel=False)
        nodes["{node_name}"].setXYpos({x}, {y + (i * 80)})
"""
                
                # Add label if specified
                if label:
                    create_template_code += f"""
        # Set label
        if "label" in nodes["{node_name}"].knobs():
            nodes["{node_name}"]["label"].setValue("{label}")
"""
                    
                # Add other parameters
                if node_params:
                    for param_name, param_value in node_params.items():
                        # Handle string parameters correctly
                        if isinstance(param_value, str):
                            param_str = f'"{param_value}"'
                        else:
                            param_str = str(param_value)
                            
                        create_template_code += f"""
        # Set parameter {param_name}
        if "{param_name}" in nodes["{node_name}"].knobs():
            nodes["{node_name}"]["{param_name}"].setValue({param_str})
"""
                        
                create_template_code += """
    except Exception as e:
        print(f"Error creating node: {str(e)}")
        import traceback
        print(traceback.format_exc())
        continue
"""
            
        # 2. Now that all nodes exist, create the connections
        create_template_code += """
    # 2. Connect nodes AFTER all have been created
    try:
"""
        
        # Connect nodes in sequence
        for i in range(1, len(template_nodes)):
            prev_node = template_nodes[i-1].get("name")
            curr_node = template_nodes[i].get("name")
            create_template_code += f"""
        # Connect {prev_node} to {curr_node}
        if "{prev_node}" in nodes and "{curr_node}" in nodes:
            nodes["{curr_node}"].setInput(0, nodes["{prev_node}"])
"""
        
        # 3. Create backdrop if requested
        if add_backdrop:
            backdrop_color = {
                "keying": "0x8A8A5BFF",       # Olive
                "color_correction": "0xC67171FF",  # Red
                "lens_distortion": "0x71C691FF",   # Green
                "3d_simple": "0x7171C6FF"      # Blue
            }.get(template_type, "0x7171C6FF")  # Default blue
            
            create_template_code += f"""
        # Create backdrop to group the nodes
        min_x = min(node.xpos() for node in nodes.values()) - 50
        max_x = max(node.xpos() for node in nodes.values()) + 150
        min_y = min(node.ypos() for node in nodes.values()) - 50
        max_y = max(node.ypos() for node in nodes.values()) + 150
        width = max_x - min_x
        height = max_y - min_y
        
        backdrop = nuke.nodes.BackdropNode(
            xpos=min_x,
            ypos=min_y,
            bdwidth=width,
            bdheight=height,
            tile_color={backdrop_color},
            note_font_size=42,
            label="{template_type.upper()}"
        )
"""
            
        # Finalize code with exception handling and result capture
        create_template_code += """
    except Exception as e:
        print(f"Error connecting nodes: {str(e)}")
        import traceback
        print(traceback.format_exc())

    # Return result with node names
    output = {
        "status": "success",
        "created_nodes": list(nodes.keys())
    }
    
except Exception as e:
    print(f"Overall error creating template: {str(e)}")
    import traceback
    print(traceback.format_exc())
    output = {
        "status": "error",
        "error": str(e)
    }
"""
        
        # Execute the code in Nuke
        logger.info(f"Creating workflow template '{template_type}' using execute_code")
        nuke = get_nuke_connection()
        result = nuke.send_command("legacy_workflow", {"code": create_template_code})
        
        if result.get("executed", False):
            output = result.get("output", {})
            status = output.get("status", "error")
            
            if status == "success":
                nodes = output.get("created_nodes", [])
                return f"Created {template_type} workflow template with nodes: {', '.join(nodes)}"
            else:
                error = output.get("error", "Unknown error")
                return f"Error creating workflow template: {error}"
        else:
            error = result.get("error", "Unknown error")
            return f"Failed to create workflow template: {error}"
    
    except Exception as e:
        logger.error(f"Error in create_workflow_template: {str(e)}")
        return f"Error creating workflow template: {str(e)}"

@bridge_tool(mcp)
def organize_node_graph(
    ctx: Context,
    selected_only: bool = False,
    direction: str = "vertical"
) -> str:
    """
    Auto-organize the node graph in a clean, professional layout.
    
    Parameters:
    - selected_only: Only organize selected nodes if True
    - direction: Layout direction, either "vertical" (top to bottom) or "horizontal" (left to right)
    """
    try:
        logger.info(f"Tool called: organize_node_graph with selected_only={selected_only}, direction={direction}")
        nuke = get_nuke_connection()
        
        # Organization code that follows the stable layout practices
        organize_code = f"""
import nuke

# Function to determine node category
def get_node_category(node):
    node_type = node.Class()
    if "Read" in node_type:
        return "INPUTS", 0
    elif "Write" in node_type:
        return "OUTPUT", 5
    elif node_type in ["Roto", "RotoPaint", "Crop", "Reformat"]:
        return "PREP", 1
    elif node_type in ["Keyer", "Primatte", "IBKColour", "IBKGizmo"]:
        return "KEY", 2
    elif node_type in ["Grade", "ColorCorrect", "HueCorrect", "ColorLookup"]:
        return "COLOR", 3
    elif node_type in ["Blur", "Glow", "VectorBlur", "ZDefocus"]:
        return "FX", 4
    else:
        return "MISC", 6

try:
    # 1. First collect all nodes and their categories
    categories = {{}}
    node_objects = {{}}
    
    for n in nuke.allNodes():
        if {selected_only.__str__().lower()} and not n.isSelected():
            continue
            
        # Skip existing backdrops
        if n.Class() == "BackdropNode":
            continue
            
        category, idx = get_node_category(n)
        if category not in categories:
            categories[category] = []
            node_objects[category] = []
            
        # Track both node names and node objects
        categories[category].append(n.name())
        node_objects[category].append(n)
    
    # Dictionary to track node coordinates for each category
    category_coords = {{}}
    
    # 2. Position the nodes with proper spacing
    x_start = 0
    for cat_idx in range(7):  # 0-6 for our categories
        # Find the category with this index
        cat_name = None
        for category, nodes in categories.items():
            if not nodes:
                continue
            if get_node_category(node_objects[category][0])[1] == cat_idx:
                cat_name = category
                break
        
        if not cat_name:
            continue
            
        # Get nodes for this category
        nodes_in_category = node_objects[cat_name]
        node_names = categories[cat_name]
        
        if not nodes_in_category:
            continue
        
        # Position nodes in this category
        min_x = x_start
        min_y = 0
        max_x = x_start + 150  # Default width
        max_y = 0
            
        # Position each node with stability-focused loop
        for i, node in enumerate(nodes_in_category):
            try:
                if "{direction}" == "vertical":
                    # Vertical positioning - only change Y
                    y_pos = i * 100  # Stable vertical spacing
                    node.setXYpos(x_start, y_pos)
                    max_y = max(max_y, y_pos + 80)  # Track max Y
                else:
                    # Horizontal positioning - only change X
                    x_pos = x_start + (i * 150)  # Stable horizontal spacing
                    node.setXYpos(x_pos, 0)
                    max_x = max(max_x, x_pos + 80)  # Track max X
            except Exception as e:
                print(f"Error positioning node {{node.name()}}: {{str(e)}}")
        
        # Store coordinates for backdrop creation
        category_coords[cat_name] = (min_x, min_y, max_x, max_y)
        
        # Increment x_start for next category
        x_start = max_x + 100  # Add spacing between categories
    
    # 3. After all nodes are positioned, create backdrops
    created_backdrops = []
    
    for category, (min_x, min_y, max_x, max_y) in category_coords.items():
        try:
            # Adjust for proper padding
            backdrop_x = min_x - 50
            backdrop_y = min_y - 50
            backdrop_width = max_x - min_x + 100
            backdrop_height = max_y - min_y + 100
            
            # Set color based on category
            backdrop_color = {{
                "INPUTS": 0x7171C6FF,  # Blue
                "PREP": 0x9292E1FF,    # Light Blue
                "KEY": 0x8A8A5BFF,     # Olive
                "COLOR": 0xC67171FF,   # Red
                "FX": 0x71C691FF,      # Green
                "OUTPUT": 0xDFDF36FF,  # Yellow
                "MISC": 0xAAAAAAAA     # Gray
            }}.get(category, 0xAAAAAAAA)
            
            # Create backdrop
            backdrop = nuke.nodes.BackdropNode(
                xpos=backdrop_x,
                ypos=backdrop_y,
                bdwidth=backdrop_width,
                bdheight=backdrop_height,
                tile_color=backdrop_color,
                note_font_size=42,
                label=category
            )
            created_backdrops.append(backdrop.name())
            
        except Exception as e:
            print(f"Error creating backdrop for {{category}}: {{str(e)}}")
    
    # Return results
    output = {{
        "status": f"Organized {{sum(len(nodes) for nodes in categories.values())}} nodes with {{direction}} flow",
        "nodes_organized": sum(len(nodes) for nodes in categories.values()),
        "backdrops_created": len(created_backdrops)
    }}
    
except Exception as e:
    import traceback
    error_traceback = traceback.format_exc()
    print(f"Error organizing node graph: {{str(e)}}")
    print(error_traceback)
    output = {{
        "status": f"Error: {{str(e)}}",
        "error": str(e)
    }}
"""
        
        # Execute the organization code
        result = nuke.send_command("legacy_workflow", {"code": organize_code})
        
        if result.get("executed", False):
            output = result.get("output", {})
            status = output.get("status", f"Organized node graph with {direction} flow direction")
            nodes_count = output.get("nodes_organized", 0)
            backdrop_count = output.get("backdrops_created", 0)
            
            if "Error:" in status:
                return f"Failed to organize nodes: {output.get('error', 'Unknown error')}"
            
            return f"{status} - Organized {nodes_count} nodes with {backdrop_count} category backdrops"
        else:
            error = result.get("error", "Unknown error")
            return f"Failed to organize nodes: {error}"
    except Exception as e:
        logger.error(f"Error in organize_node_graph: {str(e)}")
        return f"Error organizing node graph: {str(e)}"

@mcp.prompt()
def nuke_mcp_usage() -> str:
    """Provides guidance on how to use the Nuke MCP tools"""
    return """# Working with Nuke through MCP

When creating or editing composites in Nuke, follow these guidelines:

## Getting Started
1. First, use `get_script_info()` to understand the current state of the Nuke script
2. For details on specific nodes, use `get_node_info(node_name="NodeName")`

## Creating and Connecting Nodes
1. Create nodes with `create_node(node_type="Type", parameters={...})`
2. Connect nodes with `connect_nodes(output_node="Source", input_node="Target", input_index=0)`
3. For complex node trees, create nodes first, then connect them

## Node Placement
1. When creating multiple nodes, specify positions to avoid overlaps
2. For automatic arrangement, use `auto_layout_nodes()`
3. Position individual nodes with `position_node(name="NodeName", x=100, y=100)`
4. Use `organize_node_graph()` to arrange nodes by category with backdrops

## Workflow Templates
1. Create common node setups with `create_workflow_template(template_type="keying")`
2. Available templates include: "keying", "color_correction", "lens_distortion", "3d_simple"

## Rendering and Viewing
1. Control playback with `viewer_playback(action="play")`
2. Render frames with `render(frame_range="1-10", write_node="Write1")`
3. Create viewers with `create_viewer(input_node="NodeName")`

## Compositing Best Practices
1. Maintain B-pipe structure (main pipeline connects to B input of Merge nodes)
2. Use Unpremult before color correction operations
3. Keep node graph organized with a top-to-bottom, left-to-right flow
4. Use labels for descriptions instead of renaming nodes
5. Group related nodes with backdrops
"""

def main():
    """Run the NukeMCP server"""
    logger.info("Starting NukeMCP main function")
    logger.info("This server connects to Nuke and exposes MCP tools")
    logger.info("Make sure Nuke is running with the NukeMCP addon active")
    mcp.run()

if __name__ == "__main__":
    main()
