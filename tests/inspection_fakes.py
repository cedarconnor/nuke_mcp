"""Host boundary fixture; graph and filesystem assertions exercise production code."""
from types import SimpleNamespace
from tests.mutation_fakes import Host, Node, Knob

class FileKnob(Knob):
    def __init__(self, raw, evaluator):
        super().__init__(raw, 'File_Knob')
        self.evaluator = evaluator
    def getEvaluatedValue(self, context): return self.evaluator(context.frame(), context.view())

class Context:
    def __init__(self): self.f, self.v = 1, 0
    def setFrame(self, value): self.f = value
    def setView(self, value): self.v = value
    def frame(self): return self.f
    def view(self): return self.v
    def viewFromName(self, name): return ['left', 'right'].index(name)
    def viewshort(self, index): return ['l', 'r'][index]

class ImageNode(Node):
    def __init__(self, host, path, kind):
        super().__init__(host, path, kind)
        self._channels = ['rgba.red', 'rgba.green', 'rgba.blue', 'rgba.alpha']
        self._knobs.update(first=Knob(-2, 'Int_Knob'), last=Knob(2, 'Int_Knob'),
                           colorspace=Knob('linear', 'Enumeration_Knob'),
                           file=FileKnob('/plates/%04d.exr', lambda frame, view: '/plates/%04d.exr'),
                           part=Knob('beauty', 'Enumeration_Knob'))
    def channels(self): return self._channels[:]
    def format(self): return SimpleNamespace(width=lambda:4, height=lambda:4, pixelAspect=lambda:1.)
    def sample(self, channel, x, y, dx, dy):
        return self.host.sampler(channel, x, y, dx, dy)

class ImageHost(Host):
    OutputContext = Context
    def __init__(self):
        super().__init__()
        self.env = {'nc':False}
        self.current_frame = 10
        self.frame_writes = []
        self.sampler = lambda c,x,y,dx,dy: .5
    def add(self, path, kind='Grade'):
        node = ImageNode(self, path, kind)
        self.graph[path] = node
        return node
    def allNodes(self, recurseGroups=False):
        return [n for n in super().allNodes() if recurseGroups or '.' not in n.path]
    def views(self): return ['left', 'right']
    def frame(self, value=None):
        if value is not None:
            self.frame_writes.append(value)
            self.current_frame = value
        return self.current_frame
    def filenameFilter(self, path): return path
