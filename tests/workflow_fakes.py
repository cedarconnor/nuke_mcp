"""Disposable workflow host with serialized graph round trips, never native qualification."""
import json
from pathlib import Path
from types import SimpleNamespace
from tests.test_scripts import ScriptHost
from tests.library_fakes import LibraryNode
from tests.mutation_fakes import Knob
from tests.inspection_fakes import Context, FileKnob

class Enum(Knob):
    def __init__(self,value,options):super().__init__(value,'Enumeration_Knob');self.options=options
    def values(self):return self.options

class WorkflowNode(LibraryNode):
    def __init__(self,host,path,kind):
        super().__init__(host,path,kind)
        self._channels=['rgba.red','rgba.green','rgba.blue','rgba.alpha']
        self._knobs.update(file=FileKnob('',lambda f,v:self.file_value(f)),
            colorspace=Enum('linear',['linear','raw']),first=Knob(1,'Int_Knob'),last=Knob(100,'Int_Knob'),
            file_type=Enum('exr',['exr']),datatype=Enum('half',['half','float']),
            compression=Enum('Zip (1 scanline)',['Zip (1 scanline)']),channels=Enum('rgba',['rgba','rgb']),
            operation=Enum('over',['over','plus','multiply','screen']),maskChannel=Enum('rgba.alpha',['rgba.alpha']),
            **{'in':Enum('rgba',['rgba','diffuse']), 'out':Enum('rgba',['rgba']), 'red':Enum('red',['red']), 'green':Enum('green',['green']),
               'blue':Enum('blue',['blue']), 'alpha':Enum('alpha',['alpha']),
               'white':Knob(1.),'gamma':Knob(1.),'size':Knob(0.),'number':Knob(0,'Int_Knob')})
    def file_value(self,frame):
        path=self['file'].value().replace('[file dirname [value root.name]]',str(Path(self.host.script_path).parent))
        return path%frame if '%' in path else path
    def channels(self):return self._channels[:]
    def format(self):return SimpleNamespace(width=lambda:4,height=lambda:4,pixelAspect=lambda:1.)

class WorkflowHost(ScriptHost):
    GUI=True
    OutputContext=Context
    def __init__(self):
        super().__init__()
        self.modified=False
        self.current_frame=1
        self.save_hook=None
        self.open_hook=None
        self.render_count=0
    def add(self,path,kind='Grade'):
        node=WorkflowNode(self,path,kind);self.graph[path]=node;return node
    def setup(self):
        self.root()._knobs['colorManagement']=Enum('Nuke',['Nuke','OCIO'])
        for kind in ('Read','Write','Group','Input','Output','Shuffle','Grade','Blur','Merge2'):
            setattr(self.nodes,kind,lambda _kind=kind,**kw:self.create(_kind,**kw))
        return self
    def create(self,kind,**kw):
        if self.scope:kw['name']=self.scope+'.'+kw['name']
        return super().create(kind,**kw)
    def frame(self,value=None):
        if value is not None:self.current_frame=value
        return self.current_frame
    def views(self):return ['main']
    def filenameFilter(self,path):return path
    def scriptClear(self):
        super().scriptClear();self.graph.clear()
    def scriptSaveAs(self,path,overwrite):
        super().scriptSaveAs(path,overwrite)
        payload={'graph':[{'path':n.path,'kind':n.kind,'knobs':{k:v.value() for k,v in n.knobs().items()},
                          'inputs':{str(i):src.path for i,src in n.connections.items() if src}} for n in self.graph.values()]}
        Path(path).write_text(json.dumps(payload))
        if self.save_hook:self.save_hook(path)
    def scriptOpen(self,path):
        super().scriptOpen(path)
        data=json.loads(Path(path).read_text())
        self.graph.clear()
        for row in data.get('graph',[]):
            n=self.add(row['path'],row['kind'])
            for k,v in row['knobs'].items():n[k].v=v
        for row in data.get('graph',[]):
            for i,source in row['inputs'].items():self.graph[row['path']].setInput(int(i),self.graph[source])
        if self.open_hook:self.open_hook(path)
