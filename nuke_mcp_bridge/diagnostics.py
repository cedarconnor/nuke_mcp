"""Filtered grid measurements with bounded work and explicit sample coverage."""
import math
from .protocol import BridgeError
from .mutations import main_thread, check_guard, resolve_node
from .inspection import bounded_int


def channel_syntax(requested):
    if not isinstance(requested, list) or not 1 <= len(requested) <= 16 or any(
            not isinstance(c, str) or not c or len(c)>256 for c in requested):
        raise BridgeError('invalid_request', 'Request 1..16 channel or layer names')


def resolve_channels(node, requested):
    channel_syntax(requested)
    available = node.channels()
    if len(available)>2048: raise BridgeError('limit_exceeded', 'Channel discovery exceeds 2048 channels')
    resolved = []
    for name in requested:
        matches = [name] if name in available else [c for c in available if c.rsplit('.',1)[0]==name]
        if not matches: raise BridgeError('channel_unavailable', name)
        for channel in matches:
            if channel not in resolved: resolved.append(channel)
        if len(resolved)>16: raise BridgeError('limit_exceeded', 'At most 16 resolved channels')
    return resolved


def region(node, roi):
    fmt = node.format()
    width, height = fmt.width(), fmt.height()
    if width<=0 or height<=0: raise BridgeError('invalid_roi', 'Node has no positive image dimensions')
    value = [0,0,width,height] if roi is None else roi
    if not isinstance(value, (list,tuple)) or len(value)!=4 or any(type(v) is not int for v in value):
        raise BridgeError('invalid_roi', 'ROI is [x,y,width,height] in integer pixels')
    x,y,w,h = value
    if x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height:
        raise BridgeError('invalid_roi', 'ROI must be positive and within the image format')
    return list(value)


def summarize(channel, values, total):
    finite = [v for v in values if math.isfinite(v)]
    count = len(finite)
    scale = max((abs(v) for v in finite), default=0.)
    mean = scale * (math.fsum(v/scale for v in finite)/count) if scale else (0. if count else None)
    return dict(channel=channel, sample_count=len(values), expected_samples=total,
                finite_count=count, nonfinite_count=len(values)-count,
                min=min(finite) if count else None, max=max(finite) if count else None,
                mean=mean, zero_fraction=sum(v==0 for v in finite)/count if count else None,
                zero_fraction_denominator='finite_samples', complete=len(values)==total)


def sample_channel_statistics(nuke, node_path, channels, frame, roi=None,
                              max_samples_per_channel=1024, should_stop=None):
    main_thread()
    bounded_int(frame,-2147483648,2147483647,'frame')
    bounded_int(max_samples_per_channel,1,4096,'max_samples_per_channel')
    channel_syntax(channels)
    if roi is not None and (not isinstance(roi,(list,tuple)) or len(roi)!=4 or
            any(type(v) is not int for v in roi) or roi[0]<0 or roi[1]<0 or roi[2]<=0 or roi[3]<=0):
        raise BridgeError('invalid_roi','ROI is [x,y,width,height] with nonnegative origin and positive integer size')
    node = resolve_node(nuke,node_path)
    original_frame = nuke.frame()
    resolved, values = [], {}
    result = dict(path=node.fullName(), frame=frame, channels=[], roi=roi,
                  statistics=[], samples_completed=0, complete=False,
                  observation={'coverage':'partial','reason':'filtered_grid_samples'})
    failure = None
    changed_frame = False
    per_channel = 0
    def boundary():
        check_guard()
        if should_stop is not None and should_stop(): raise BridgeError('cancelled','Sampling cancelled')
    try:
        boundary()
        if original_frame != frame:
            changed_frame = True
            nuke.frame(frame)
        if nuke.frame()!=frame: raise RuntimeError('Requested frame was not established')
        # Formats and channels belong to the requested frame, not the artist's current frame.
        area = region(node,roi)
        resolved = resolve_channels(node,channels)
        values = {c:[] for c in resolved}
        result['channels'] = resolved
        result['roi'] = area
        x,y,w,h = area
        nx = min(w,max(1,int(math.sqrt(max_samples_per_channel*w/h))))
        nx = min(nx,max_samples_per_channel)
        ny = min(h,max(1,max_samples_per_channel//nx))
        per_channel = nx*ny
        dx,dy = w/nx,h/ny
        result['sampling'] = dict(method='nuke.Node.sample_cubic_filtered_grid', grid=[nx,ny],
            tile_size=[dx,dy], first_center=[x+dx/2,y+dy/2], samples_per_channel=per_channel,
            requested_max=max_samples_per_channel, samples_every_pixel=False,
            extrema_scope='filtered_samples_only',
            limitations='Filtered samples do not prove all pixels are black or establish full-image extrema.')
        for channel in resolved:
            for row in range(ny):
                for col in range(nx):
                    boundary()
                    value = float(node.sample(channel,x+(col+.5)*dx,y+(row+.5)*dy,dx,dy))
                    values[channel].append(value)
                    result['samples_completed'] += 1
        result['complete'] = True
    except Exception as exc:
        failure = exc
    finally:
        try:
            if changed_frame: nuke.frame(original_frame)
            if nuke.frame()!=original_frame: raise RuntimeError('Original frame not restored')
            result['frame_restored'] = True
        except Exception as exc:
            result['frame_restored'] = False
            result['restoration_error'] = str(exc)[:256]
            if failure: result['prior_error'] = str(failure)[:256]
            raise BridgeError('restoration_failed','Frame restoration failed','unknown',result) from exc
    try:
        result['statistics'] = [summarize(c,values[c],per_channel) for c in resolved]
    except Exception as exc:
        result['complete'] = False
        raise BridgeError('statistics_failed',str(exc),'not_started',result) from exc
    if failure:
        raise BridgeError(getattr(failure,'code','sampling_failed'),str(failure),'not_started',result) from failure
    return result
