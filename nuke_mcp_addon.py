import nuke
import nukescripts
import json
import threading
import socket
import time
import traceback
import os
from typing import Dict, Any, List, Optional, Union

_DEBUG_LOG_PATH = os.environ.get("NUKE_MCP_DEBUG_LOG")
DEFAULT_PORT = int(os.environ.get("NUKE_MCP_PORT", "9877"))


def _debug_log(message):
    """Write bridge diagnostics without depending on a visible Nuke console."""
    if not _DEBUG_LOG_PATH:
        return
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        thread_name = threading.current_thread().name
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(
                "[{0}] [{1}] {2}\n".format(timestamp, thread_name, message)
            )
    except Exception:
        pass


_debug_log("Loaded add-on module from {0}".format(os.path.abspath(__file__)))


class NukeMCPServer:
    def __init__(self, host="localhost", port=DEFAULT_PORT):
        self.host, self.port = host, port
        self.running = False
        self.runtime = None
        self._valid_node_types = None

    def start(self):
        from nuke_mcp_bridge.operations import OperationRegistry
        from nuke_mcp_bridge.runtime import BridgeRuntime, QtDispatcher
        if self.running:
            return True
        names = ("get_script_info", "create_node", "modify_node", "delete_node",
                 "position_node", "connect_nodes", "render", "viewer_playback",
                 "execute_code", "auto_layout", "get_node_info", "set_frames", "create_viewer",
                 "batch_edit", "legacy_workflow", "inspect_graph", "inspect_reads", "validate_reads",
                 "sample_channel_statistics", "list_toolsets", "save_toolset", "load_toolset",
                 "open_script", "save_script", "set_project_settings", "import_shot_csv",
                 "plan_shot_setup", "apply_shot_setup")
        handlers = {name: self._checked_handler(getattr(self, name)) for name in names}
        from nuke_mcp_bridge.capabilities import probe_capabilities
        handlers["get_capabilities"] = lambda: probe_capabilities(nuke)
        self.runtime = BridgeRuntime(handlers, OperationRegistry(), QtDispatcher())
        try:
            self.runtime.start(self.host, self.port)
            self.running = True
            _debug_log("Protocol v2 started: " + self.runtime.registry.instance_id)
            return True
        except Exception:
            self.runtime.stop()
            self.runtime = None
            raise

    @staticmethod
    def _checked_handler(handler):
        def checked(**params):
            from nuke_mcp_bridge.protocol import BridgeError
            result = handler(**params)
            if isinstance(result, dict) and (result.get("error") or
                    result.get("executed") is False or result.get("status") == "error"):
                raise BridgeError("host_error", str(result.get("error") or result.get("message")),
                                  outcome="unknown", data=result)
            # Legacy execute_code nests workflow outcomes in output.
            output = result.get("output") if isinstance(result, dict) else None
            if isinstance(output, dict) and (output.get("status") == "error" or output.get("error")):
                raise BridgeError("host_error", str(output.get("error")), outcome="unknown", data=result)
            return result
        return checked

    def stop(self):
        if self.runtime:
            self.runtime.stop()
            self.runtime = None
        self.running = False

    def _get_valid_node_types(self):
        """Return a list of valid Nuke node types to prevent crashes."""
        # Use cached list if available
        if self._valid_node_types is not None:
            return self._valid_node_types
            
        # Standard Nuke node types that should always be available
        standard_node_types = [
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
            # Special nodes
            "BackdropNode"
        ]
        
        # Try to get actual node classes from environment if possible
        try:
            all_nodes = set(standard_node_types)
            
            # Add any nodes from menu
            try:
                menu_items = nuke.menu("Nodes").items()
                for item in menu_items:
                    if hasattr(item, 'name'):
                        all_nodes.add(item.name())
            except:
                print("Warning: Could not get node types from menu")
                
            # Store the combined list
            self._valid_node_types = list(all_nodes)
            print(f"Found {len(self._valid_node_types)} valid node types")
            
        except Exception as e:
            # Fallback to standard list
            print(f"Warning: Using fallback node list due to error: {str(e)}")
            self._valid_node_types = standard_node_types
            
        return self._valid_node_types
        
    def _normalize_node_type(self, node_type):
        """
        Convert common incorrect node type names to their proper equivalents.
        Returns the correct node type name or None if no match found.
        """
        # Mapping of incorrect to correct node types
        node_type_corrections = {
            # Common mistakes
            "Output": "Write",
            "WriteNode": "Write",
            "Input": "Read",
            "ReadNode": "Read",
            "Merge": "Merge2",
            "ColorCorrection": "ColorCorrect",
            "Color": "Grade",
            "Grading": "Grade",
            "Gaussian": "Blur",
            "GaussianBlur": "Blur",
            "BlurNode": "Blur",
            "Premultiply": "Premult", 
            "PreMult": "Premult",
            "Unpremultiply": "Unpremult",
            "UnPreMult": "Unpremult",
            "Move": "Transform",
            "Position": "Transform",
            "Rectangle": "Crop",
            "CropNode": "Crop",
        }
        
        # Check for exact match first
        valid_types = self._get_valid_node_types()
        if node_type in valid_types:
            return node_type
            
        # Check for known corrections
        if node_type in node_type_corrections:
            corrected_type = node_type_corrections[node_type]
            print(f"Corrected node type '{node_type}' to '{corrected_type}'")
            return corrected_type
            
        # No correction found
        return None
        
    def _validate_node_name(self, name):
        """
        Validate a node name to prevent problematic naming patterns.
        Returns a safe version of the name.
        """
        if not name:
            return None
        
        # Check if name starts with a number
        if name[0].isdigit():
            print(f"Warning: Node name '{name}' starts with a number, which can cause issues")
            # Prefix with a safe character (n_)
            name = f"n_{name}"
        
        # Replace any invalid characters
        # Nuke node names should only contain alphanumeric and underscore
        import re
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        
        if safe_name != name:
            print(f"Warning: Node name '{name}' contained invalid characters, using '{safe_name}' instead")
        
        return safe_name
    
    def inspect_graph(self, **kwargs):
        from nuke_mcp_bridge.inspection import inspect_graph
        return inspect_graph(nuke, **kwargs)

    def list_toolsets(self):
        from nuke_mcp_bridge.toolsets import list_toolsets, library_root
        return list_toolsets(library_root())

    def open_script(self, **kwargs):
        from nuke_mcp_bridge.scripts import open_script
        return open_script(nuke, **kwargs)

    def import_shot_csv(self, **kwargs):
        from nuke_mcp_bridge.manifests import import_shot_csv
        return import_shot_csv(**kwargs)

    def plan_shot_setup(self, manifest):
        from nuke_mcp_bridge.shots import plan_shot_setup
        from nuke_mcp_bridge.toolsets import library_root
        return plan_shot_setup(nuke,manifest,library_root())

    def apply_shot_setup(self, manifest, plan_digest):
        from nuke_mcp_bridge.shots import apply_shot_setup
        from nuke_mcp_bridge.toolsets import library_root
        return apply_shot_setup(nuke,manifest,plan_digest,library_root(),self.runtime.registry)

    def save_script(self, **kwargs):
        from nuke_mcp_bridge.scripts import save_script
        return save_script(nuke, **kwargs)

    def set_project_settings(self, **kwargs):
        from nuke_mcp_bridge.scripts import set_project_settings
        return set_project_settings(nuke, **kwargs)

    def save_toolset(self, **kwargs):
        from nuke_mcp_bridge.toolsets import save_toolset, library_root
        return save_toolset(nuke, library_root(), **kwargs)

    def load_toolset(self, **kwargs):
        from nuke_mcp_bridge.toolsets import load_toolset, library_root
        return load_toolset(nuke, library_root(), **kwargs)

    def sample_channel_statistics(self, **kwargs):
        from nuke_mcp_bridge.diagnostics import sample_channel_statistics
        return sample_channel_statistics(nuke, **kwargs)

    def inspect_reads(self, **kwargs):
        from nuke_mcp_bridge.inspection import inspect_reads
        return inspect_reads(nuke, **kwargs)

    def validate_reads(self, **kwargs):
        from nuke_mcp_bridge.inspection import validate_reads
        return validate_reads(nuke, **kwargs)

    def get_script_info(self):
        """Legacy overview uses the same bounded graph observation."""
        from nuke_mcp_bridge.inspection import error_field
        result = self.inspect_graph()
        try:
            root = nuke.root()
            result.update(name=root.name(), fps=root.fps(), format=str(root.format()),
                          first_frame=root['first_frame'].value(), last_frame=root['last_frame'].value())
        except Exception as exc:
            result['errors'].append(error_field('script', exc))
            result['observation'] = {'coverage':'unknown', 'reason':'script_unavailable'}
        return result

    def create_node(self, node_type, name=None, position=None, inputs=None, parameters=None):
        from nuke_mcp_bridge.mutations import create_node
        return create_node(nuke, node_type, name, position, inputs, parameters)

    def batch_edit(self, operations, dry_run=True, expected_revision=None):
        from nuke_mcp_bridge.batch import execute_batch
        return execute_batch(nuke, operations, dry_run, expected_revision)

    def modify_node(self, name, parameters=None, position=None, inputs=None):
        from nuke_mcp_bridge.mutations import resolve_node
        from nuke_mcp_bridge.protocol import BridgeError
        node = resolve_node(nuke, name)
        operations = []
        if parameters is not None:
            if not isinstance(parameters, dict): raise BridgeError('invalid_request', 'parameters must be an object')
            operations.extend(dict(op='set_knob', node_path=name, knob=k, value=v) for k,v in parameters.items())
        if position is not None:
            if not isinstance(position, (tuple,list)) or len(position) != 2:
                raise BridgeError('invalid_request', 'Position requires two coordinates')
            operations.append(dict(op='position', node_path=name, x=position[0], y=position[1]))
        if inputs is not None:
            if not isinstance(inputs,list): raise BridgeError('invalid_request', 'inputs must be a list')
            operations.extend(dict(op='connect', node_path=name, input_index=i, source_path=source)
                              for i,source in enumerate(inputs))
        identity = dict(name=node.name(), path=node.fullName(), type=node.Class())
        result = self.batch_edit(operations, dry_run=False) if operations else {'outcome':'not_started','items':[]}
        return dict(result, **identity)

    def legacy_workflow(self, code):
        from nuke_mcp_bridge.protocol import BridgeError
        result = self.execute_code(code)
        raise BridgeError('unverified_workflow',
                          'Legacy workflow ran without full readback; inspect state and do not replay',
                          'unknown', result)

    def delete_node(self, name):
        from nuke_mcp_bridge.mutations import delete_node
        return delete_node(nuke, name)

    def position_node(self, name, position):
        from nuke_mcp_bridge.mutations import position_node
        from nuke_mcp_bridge.protocol import BridgeError
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            raise BridgeError('invalid_value', 'Position requires x and y')
        return position_node(nuke, name, *position)

    def connect_nodes(self, output_node, input_node, input_index=0):
        from nuke_mcp_bridge.mutations import connect_input
        result = connect_input(nuke, input_node, input_index, output_node)
        return dict(result, output_node=result['source_path'], input_node=result['path'])

    def render(self, frame_range=None, write_node=None, proxy_mode=False,
               first_frame=None, last_frame=None, step=1):
        """Cooperative render: one native frame per main-thread queue tick."""
        from nuke_mcp_bridge.protocol import BridgeError
        if type(step) is not int or step < 1:
            raise BridgeError("invalid_request", "Render step must be a positive integer")
        if frame_range is not None:
            frames = self._parse_frame_range(frame_range)
        else:
            first = int(nuke.root()["first_frame"].value()) if first_frame is None else first_frame
            last = int(nuke.root()["last_frame"].value()) if last_frame is None else last_frame
            if type(first) is not int or type(last) is not int or last < first:
                raise BridgeError("invalid_request", "Render requires ordered integer frames")
            if (last - first) // step + 1 > 100000:
                raise BridgeError("invalid_request", "At most 100000 render frames")
            frames = range(first, last + 1, step)
        if write_node:
            node = nuke.toNode(write_node)
            if node is None or node.Class() != "Write":
                raise BridgeError("write_node_unavailable", "Write node unavailable: " + write_node)
            nodes = [node]
        else:
            if (nuke.env.get("nc", "unknown") is True or
                    nuke.env.get("noncommercial", "unknown") is True):
                raise BridgeError("state_uncertain", "NC enumeration cannot establish all Write nodes; specify write_node")
            nodes = nuke.allNodes("Write")
            if not nodes:
                raise BridgeError("write_node_unavailable", "No observable Write nodes")
        original_frame, original_proxy = nuke.frame(), nuke.proxy()
        completed = []
        try:
            nuke.setProxy(proxy_mode)
            for frame in frames:
                for node in nodes:
                    nuke.execute(node, frame, frame)
                completed.append(frame)
                yield {"frames_completed": list(completed),
                       "write_nodes": [node.name() for node in nodes],
                       "status": "Rendered {0} frame(s)".format(len(completed))}
        finally:
            try:
                nuke.setProxy(original_proxy)
            finally:
                nuke.frame(original_frame)

    def _parse_frame_range(self, frame_range_str):
        import re
        from nuke_mcp_bridge.protocol import BridgeError
        frames = set()
        for part in frame_range_str.split(","):
            match = re.fullmatch(r"\s*(-?\d+)(?:\s*-\s*(-?\d+))?\s*", part)
            if not match:
                raise BridgeError("invalid_request", "Invalid frame range")
            first = int(match.group(1))
            last = int(match.group(2)) if match.group(2) is not None else first
            if last < first or last - first + 1 > 100000:
                raise BridgeError("invalid_request", "Invalid or oversized frame range")
            frames.update(range(first, last + 1))
            if len(frames) > 100000:
                raise BridgeError("invalid_request", "At most 100000 render frames")
        return sorted(frames)

    def viewer_playback(self, action="play", start_frame=None, end_frame=None, viewer_index=1):
        """Control Nuke's Viewer playback"""
        try:
            # Get the viewer
            viewer = nuke.activeViewer()
            if not viewer:
                raise ValueError("No active viewer")
            
            # Set frame range if specified
            if start_frame is not None and end_frame is not None:
                viewer.frameRange(start_frame, end_frame)
            
            # Execute requested action
            if action == "play":
                viewer.play()
                return {"status": "Playing in viewer"}
            elif action == "stop":
                viewer.stop()
                return {"status": "Stopped playback"}
            elif action == "next":
                nuke.frame(nuke.frame() + 1)
                return {"status": f"Advanced to frame {nuke.frame()}"}
            elif action == "prev":
                nuke.frame(nuke.frame() - 1)
                return {"status": f"Moved back to frame {nuke.frame()}"}
            else:
                raise ValueError(f"Unknown playback action: {action}")
        
        except Exception as e:
            print(f"Viewer playback error: {str(e)}")
            traceback.print_exc()
            raise Exception(f"Viewer playback error: {str(e)}")
    
    def execute_code(self, code):
        """Execute arbitrary Python code in Nuke with safety measures"""
        try:
            if not code.strip():
                return {"executed": False, "error": "Empty code provided"}
            
            # Create a dictionary to capture output
            output = {}
            
            # Create a local namespace for execution with safety
            namespace = {"nuke": nuke, "nukescripts": nukescripts, "output": output}
            
            # Execute the code with safety wrapper
            try:
                exec(code, namespace)
                return {"executed": True, "output": output}
            except Exception as e:
                error_tb = traceback.format_exc()
                print(f"Code execution error: {str(e)}")
                print(error_tb)
                return {"executed": False, "error": str(e), "traceback": error_tb}
        except Exception as e:
            print(f"Error in execute_code setup: {str(e)}")
            traceback.print_exc()
            return {"executed": False, "error": str(e)}
    
    def auto_layout(self, selected_only=False):
        """Automatically arrange nodes in the script"""
        try:
            # Improved auto_layout implementation that avoids the "expecting a Nuke node type" error
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
output["status"] = result
            """
            
            # Execute the code
            result = self.legacy_workflow(auto_layout_code)
            
            if result.get("executed", False):
                output = result.get("output", {})
                status = output.get("status", "Nodes arranged")
                return {"status": status}
            else:
                error = result.get("error", "Unknown error")
                raise Exception(f"Failed to auto-layout nodes: {error}")
        except Exception as e:
            print(f"Auto layout error: {str(e)}")
            traceback.print_exc()
            raise Exception(f"Auto layout error: {str(e)}")
    
    def get_node_info(self, name):
        from nuke_mcp_bridge.inspection import node_record, observation
        from nuke_mcp_bridge.mutations import resolve_node
        result = node_record(resolve_node(nuke, name))
        result['observation'] = observation(nuke, 1, result['truncated'] or bool(result['errors'] or result['omitted_knobs']))
        return result

    def set_frames(self, first_frame=None, last_frame=None, current_frame=None):
        """Set frame range and current frame"""
        try:
            # Update frame range if specified
            if first_frame is not None:
                nuke.root()["first_frame"].setValue(first_frame)
            
            if last_frame is not None:
                nuke.root()["last_frame"].setValue(last_frame)
            
            # Update current frame if specified
            if current_frame is not None:
                nuke.frame(current_frame)
            
            # Return current settings
            return {
                "first_frame": nuke.root()["first_frame"].value(),
                "last_frame": nuke.root()["last_frame"].value(),
                "current_frame": nuke.frame()
            }
        except Exception as e:
            print(f"Error setting frames: {str(e)}")
            traceback.print_exc()
            raise Exception(f"Failed to set frames: {str(e)}")
    
    def create_viewer(self, input_node=None):
        """Create a Viewer node connected to the specified input node"""
        try:
            # Create the Viewer node - Viewer nodes should use nuke.nodes.Viewer() for stability
            try:
                viewer = nuke.nodes.Viewer()
                
                # Set position to a default offscreen value to avoid overlapping with other nodes
                viewer.setXYpos(0, -300)
            except Exception as e:
                print(f"Error creating Viewer using nuke.nodes.Viewer(): {str(e)}")
                # Fallback to regular createNode method
                viewer = nuke.createNode("Viewer", inpanel=False)
            
            # Connect to input node if specified
            if input_node:
                input_n = nuke.toNode(input_node)
                if not input_n:
                    raise ValueError(f"Input node not found: {input_node}")
                
                viewer.setInput(0, input_n)
            
            return {
                "name": viewer.name(),
                "position": [viewer.xpos(), viewer.ypos()],
                "connected_to": input_node
            }
        except Exception as e:
            print(f"Error creating viewer: {str(e)}")
            traceback.print_exc()
            raise Exception(f"Failed to create viewer: {str(e)}")

class NukeMCPPanel(nukescripts.PythonPanel):
    def __init__(self):
        nukescripts.PythonPanel.__init__(self, 'Nuke MCP', 'com.example.NukeMCP')
        
        # Add port field
        self.port = nuke.Int_Knob('port', 'Port:')
        self.port.setValue(DEFAULT_PORT)
        self.addKnob(self.port)
        
        # Add status field
        self.status = nuke.Text_Knob('status', 'Status:')
        self.status.setValue('Not connected')
        self.addKnob(self.status)
        
        # Add divider
        self.divider = nuke.Text_Knob('divider', '')
        self.addKnob(self.divider)
        
        # Add start button
        self.start_button = nuke.PyScript_Knob('start', 'Start Server')
        self.start_button.setFlag(nuke.STARTLINE)
        self.addKnob(self.start_button)
        
        # Add stop button
        self.stop_button = nuke.PyScript_Knob('stop', 'Stop Server')
        self.stop_button.setEnabled(False)
        self.addKnob(self.stop_button)
        
        # Store the server instance
        self.server = None
    
    def knobChanged(self, knob):
        """Handle knob changes"""
        if knob == self.start_button:
            self._start_server()
        elif knob == self.stop_button:
            self._stop_server()
    
    def _start_server(self):
        """Start the MCP server"""
        if self.server is None:
            port = int(self.port.value())
            self.server = NukeMCPServer(port=port)
            
            if self.server.start():
                self.status.setValue(f'Running on port {port}')
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                self.port.setEnabled(False)
            else:
                self.status.setValue('Failed to start server')
                self.server = None
    
    def _stop_server(self):
        """Stop the MCP server"""
        if self.server:
            self.server.stop()
            self.server = None
            
            self.status.setValue('Not connected')
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.port.setEnabled(True)

# Global instance of the panel
_panel = None

def show_panel():
    """Show the NukeMCP panel"""
    global _panel
    if _panel is None:
        _panel = NukeMCPPanel()
    _panel.show()

# Add menu item
nuke.menu('Nuke').addCommand('NukeMCP/Show Panel', show_panel)
