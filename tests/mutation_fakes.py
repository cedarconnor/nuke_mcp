"""Small stateful Nuke substitute for mutation contract tests."""
import threading
from types import SimpleNamespace

class Knob:
    def __init__(self, value=1.0, kind='Double_Knob'):
        self.v, self.kind = value, kind
        self.animated = self.expression = self.ignore = self.fail_after = False
    def Class(self): return self.kind
    def arraySize(self): return len(self.v) if isinstance(self.v, list) else 1
    def isAnimated(self): return self.animated
    def hasExpression(self): return self.expression
    def value(self): return self.v[:] if isinstance(self.v, list) else self.v
    def values(self): return ['linear', 'sRGB']
    def setValue(self, value, index=None):
        assert threading.current_thread() is threading.main_thread()
        if not self.ignore:
            if index is None: self.v = value
            else: self.v[index] = value
        if self.fail_after: raise RuntimeError('write happened, response failed')

class Node:
    def __init__(self, host, path, kind='Grade'):
        self.host, self.path, self.kind = host, path, kind
        self.xy = [0, 0]
        self.selected = False
        self.connections = {}
        self.ignore_input = self.ignore_position = False
        self._knobs = {'gain': Knob(), 'label': Knob('', 'String_Knob'),
                       'translate': Knob([0., 0.], 'XY_Knob'), 'knobChanged': Knob('', 'String_Knob')}
    def fullName(self): return self.path
    def name(self): return self.path.rsplit('.', 1)[-1]
    def Class(self): return self.kind
    def knobs(self): return self._knobs
    def knob(self, key): return self._knobs.get(key)
    def __getitem__(self, key): return self._knobs[key]
    def setName(self, name):
        self.host.graph.pop(self.path)
        self.path = name
        self.host.graph[name] = self
    def setSelected(self, value): self.selected = value
    def isSelected(self): return self.selected
    def setXYpos(self, x, y):
        if not self.ignore_position: self.xy = [x, y]
    def xpos(self): return self.xy[0]
    def ypos(self): return self.xy[1]
    def maxInputs(self): return 4
    def inputs(self): return max(self.connections, default=-1) + 1
    def canSetInput(self, i, node): return node is not self
    def setInput(self, i, node):
        if not self.ignore_input: self.connections[i] = node
    def input(self, i): return self.connections.get(i)

class Host:
    def __init__(self):
        self.graph = {}
        self.env = {'nc': True}
        self.create_count = 0
        self.deleted = []
        self.create_returns_none = self.blackout = self.fail_delete = False
        self.destroy_callbacks = []
        self.active_destroy = None
        self.emit_destroy = True
        self.nodes = SimpleNamespace(Grade=lambda **kw: self.create('Grade', **kw),
                                     StudioPlugin=lambda **kw: self.create('StudioPlugin', **kw))
        self.undo_begins = self.undo_ends = self.global_undos = 0
        self.Undo = lambda: SimpleNamespace(begin=self.begin, end=self.end)
    def begin(self, label): self.undo_begins += 1
    def end(self): self.undo_ends += 1
    def root(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def add(self, path, kind='Grade'):
        node = Node(self, path, kind)
        self.graph[path] = node
        return node
    def createNode(self, kind, **kwargs): return self.create(kind, **kwargs)
    def create(self, kind, **kwargs):
        if 'inpanel' in kwargs: raise RuntimeError('knob inpanel cannot be found.')
        self.create_count += 1
        name = kwargs.get('name', kind + str(self.create_count))
        while name in self.graph: name += '_1'
        node = self.add(name, kind)
        return None if self.create_returns_none else node
    def toNode(self, path): return None if self.blackout else self.graph.get(path)
    def allNodes(self, **kwargs): return [] if self.blackout else list(self.graph.values())
    def selectedNodes(self): return [n for n in self.graph.values() if n.selected]
    def addOnDestroy(self, fn, **kwargs): self.destroy_callbacks.append(fn)
    def removeOnDestroy(self, fn, **kwargs): self.destroy_callbacks.remove(fn)
    def thisNode(self): return self.active_destroy
    def delete(self, node):
        if self.fail_delete: raise RuntimeError('delete failed')
        self.active_destroy = node
        if self.emit_destroy:
            for callback in self.destroy_callbacks[:]: callback()
        self.graph.pop(node.path)
        self.deleted.append(node.path)
