"""Explicit callback surface, without a native Nuke dependency."""
from types import SimpleNamespace
from tests.mutation_fakes import Host


class EventHost(Host):
    NUKE_VERSION_MAJOR = 17
    NUKE_VERSION_STRING = '17.0v4'

    def __init__(self, nc=False):
        super().__init__()
        self.env = {'nc': nc}
        self.callbacks = {}
        self.current_node = None
        self.current_knob = None
        self.script_name = 'Root'
        self.current_frame = 1
        for suffix in ('OnCreate', 'OnDestroy', 'KnobChanged', 'OnScriptLoad',
                       'OnScriptSave', 'OnScriptClose', 'UpdateUI'):
            setattr(self, 'add'+suffix, self.adder(suffix))
            setattr(self, 'remove'+suffix, self.remover(suffix))

    def adder(self, suffix):
        def add(fn, **kwargs):
            self.callbacks.setdefault(suffix, []).append((fn, kwargs))
        return add

    def remover(self, suffix):
        def remove(fn, **kwargs):
            self.callbacks[suffix].remove((fn, kwargs))
        return remove

    def emit(self, suffix, node=None, knob='gain'):
        self.current_node = node or self
        self.current_knob = SimpleNamespace(name=lambda: knob)
        for fn, _ in list(self.callbacks.get(suffix, [])):
            fn()

    def thisNode(self): return self.current_node
    def thisKnob(self): return self.current_knob
    def name(self): return self.script_name
    def fullName(self): return 'root'
    def frame(self): return self.current_frame

    def emitting_knob(self, node, key):
        original = node[key].setValue
        def setter(value, index=None):
            original(value, index)
            self.emit('KnobChanged', node, key)
        node[key].setValue = setter
