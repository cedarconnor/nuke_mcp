"""Stateful host boundary for library and lifecycle contracts."""
import json
from pathlib import Path
from types import SimpleNamespace
from tests.mutation_fakes import Host, Node, Knob

class LibraryNode(Node):
    def __enter__(self):
        self.previous_scope = self.host.scope
        self.host.scope = '' if self.path=='root' else self.path
        return self
    def __exit__(self,*args): self.host.scope = self.previous_scope
    def nodes(self): return self.host.children(self.path)

class LibraryHost(Host):
    NUKE_VERSION_STRING='fixture'
    def __init__(self):
        super().__init__()
        self.scope = ''
        self.root_node = LibraryNode(self,'root','Root')
        self.nodes.Group = lambda **kw:self.create('Group',**kw)
        self.copy_count = self.paste_count = 0
        self.copy_hook = self.paste_hook = None
        self.fail_copy = self.fail_paste = False
    def root(self): return self.root_node
    def add(self,path,kind='Grade'):
        n=LibraryNode(self,path,kind)
        self.graph[path]=n
        return n
    def children(self,path):
        prefix='' if path=='root' else path
        return [n for n in self.graph.values() if n.path.rpartition('.')[0]==prefix]
    def allNodes(self,recurseGroups=False,group=None):
        if self.blackout: return []
        prefix=group.path if group else self.scope
        if prefix=='root': prefix=''
        return [n for n in self.graph.values() if (n.path.startswith(prefix+'.') if prefix else True)
                and (recurseGroups or n.path.rpartition('.')[0]==prefix)]
    def nodeCopy(self,path):
        self.copy_count += 1
        nodes=[n for n in self.allNodes() if n.selected]
        selected_paths={n.path for n in nodes}
        # Include descendants of selected Group nodes in the serialized fixture.
        nodes += [n for n in self.allNodes(recurseGroups=True) if any(n.path.startswith(p+'.') for p in selected_paths)]
        payload=[]
        for n in nodes:
            relative=n.path[len(self.scope)+1:] if self.scope else n.path
            payload.append({'path':relative,'kind':n.kind,'knobs':{k:v.value() for k,v in n._knobs.items()},
                            'inputs':{str(i): src.path[len(self.scope)+1:] if self.scope else src.path
                                      for i,src in n.connections.items() if src is not None and src in nodes}})
        Path(path).write_text(json.dumps(payload))
        if self.copy_hook: self.copy_hook(path)
        if self.fail_copy: raise RuntimeError('copy failed after write')
        return bool(nodes)
    def nodePaste(self,path):
        self.paste_count += 1
        if self.paste_hook: self.paste_hook(path)
        if self.fail_paste: raise RuntimeError('paste failed')
        payload=json.loads(Path(path).read_text())
        for row in payload:
            n=self.add(self.scope+'.'+row['path'],row['kind'])
            for k,v in row['knobs'].items():
                if k in n._knobs:n[k].v=v
        for row in payload:
            n=self.graph[self.scope+'.'+row['path']]
            for i,source in row['inputs'].items(): n.setInput(int(i),self.graph[self.scope+'.'+source])
        return n if payload else None
