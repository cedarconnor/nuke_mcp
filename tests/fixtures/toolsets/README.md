# Toolset fixtures

`tests/test_toolsets.py` builds disposable libraries and stateful host fixtures at runtime.
It tests immutable publication, interrupted replacement, corrupt metadata, payload digest changes,
nested Groups, missing dependencies, selection callbacks, and actual Windows junction containment.

Native qualification must use a newly owned disposable Nuke session: create two connected nodes,
set a known static knob, save both paths, load into a new Group, and compare full relative paths,
indexed inputs and the known knob. Record actual observation limits separately from fake-host tests.
