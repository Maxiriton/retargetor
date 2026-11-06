# type: ignore
"""A character's prompt segments in Blender (object.retargetor.segments), read and written as a core.segments track.

The segments stay contiguous: editing a start or an end moves the boundary with the neighbour (core.segments),
within the lengths allowed (MIN_SEGMENT_SECONDS, the active backend's longest motion).
"""
import re

import bpy

from .core import segments as core_segments
from .core.segments import PromptSegment

# Shortest segment, in seconds: a backend's transition (Kimodo: 5 frames at 30 fps) needs room
MIN_SEGMENT_SECONDS = 0.5
# Length of a segment added at the end of the track, in seconds
NEW_SEGMENT_SECONDS = 2.0

# While True, the update callbacks of the segments' frames do nothing (track written from code)
_updating = False


def scene_fps(scene):
    return scene.render.fps / scene.render.fps_base


def length_limits(context):
    """(min_frames, max_frames or None) of a segment in the scene, with the active backend"""
    from .preferences import active_backend
    fps = scene_fps(context.scene)
    min_frames = max(2, round(MIN_SEGMENT_SECONDS * fps))
    max_duration = active_backend(context).capabilities.max_duration
    max_frames = int(max_duration * fps + 1e-6) if max_duration is not None else None
    return min_frames, max_frames


def read_track(state):
    """The character's segments (RTGTR_CharacterState) as a list of core PromptSegment"""
    return [PromptSegment(item.frame_start, item.frame_end, item.prompt, item.seed) for item in state.segments]


def write_track(state, track, active=None):
    """Make the character's segments match a track: items added or removed at the end, every field written.
    active: index of the active segment afterwards (None: kept, within the track)."""
    global _updating
    previous, _updating = _updating, True
    try:
        items = state.segments
        while len(items) > len(track):
            items.remove(len(items) - 1)
        while len(items) < len(track):
            items.add()
        for item, segment in zip(items, track):
            if item.frame_start != segment.start_frame:
                item.frame_start = segment.start_frame
            if item.frame_end != segment.end_frame:
                item.frame_end = segment.end_frame
            if item.prompt != segment.prompt:
                item.prompt = segment.prompt
            if segment.seed is not None and item.seed != segment.seed:
                item.seed = segment.seed
        index = state.segments_active_index if active is None else active
        index = max(0, min(index, len(track) - 1))
        if state.segments_active_index != index:
            state.segments_active_index = index
    finally:
        _updating = previous
    tag_redraw()


def active_segment(state):
    """The active segment item, or None"""
    if 0 <= state.segments_active_index < len(state.segments):
        return state.segments[state.segments_active_index]
    return None


_INDEX = re.compile(r"segments\[(\d+)\]")


def _owner(item):
    """(character state, index) of a segment item"""
    match = _INDEX.search(item.path_from_id())
    return item.id_data.retargetor, int(match.group(1))


def _frames_updated(item, context, which):
    """A start or end edited in the panel: the boundary moves, the neighbour adapts, within the limits. The
    track's own start and end only change the length of their segment, within the limits."""
    if _updating or context is None:
        return
    state, index = _owner(item)
    min_frames, max_frames = length_limits(context)
    track = read_track(state)
    count = len(track)
    if which == "start" and index > 0:
        new = track[index].start_frame
        track[index].start_frame = track[index - 1].end_frame + 1
        track = core_segments.move_boundary(track, index, new, min_frames, max_frames)
    elif which == "end" and index < count - 1:
        new = track[index].end_frame
        track[index].end_frame = track[index + 1].start_frame - 1
        track = core_segments.move_boundary(track, index + 1, new + 1, min_frames, max_frames)
    else:
        segment = track[index]
        longest = max_frames if max_frames is not None else segment.frame_count
        length = max(min_frames, min(longest, segment.frame_count))
        if which == "start":
            segment.start_frame = segment.end_frame - length + 1
        else:
            segment.end_frame = segment.start_frame + length - 1
    write_track(state, track)


def update_start(self, context):
    _frames_updated(self, context, "start")


def update_end(self, context):
    _frames_updated(self, context, "end")


def update_redraw(_self, _context):
    tag_redraw()


def generated_signature(segment):
    """What a generation of the segment depended on (frames, prompt, seed), to tell when it was edited since"""
    return f"{segment.frame_start}|{segment.frame_end}|{segment.seed}|{segment.prompt}"


def segment_state(item):
    """'GENERATED', 'MODIFIED' (edited since its last generation) or 'NEW' (never generated)"""
    if not item.generated:
        return 'NEW'
    return 'GENERATED' if item.generated == generated_signature(item) else 'MODIFIED'


def mark_generated(state):
    """After a generation of the whole track: every segment is up to date"""
    for item in state.segments:
        item.generated = generated_signature(item)
    tag_redraw()


def tag_redraw():
    """Redraw the editors showing the segments, and the sidebar"""
    window_manager = bpy.context.window_manager
    if window_manager is None:
        return
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type in ('VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR'):
                area.tag_redraw()
