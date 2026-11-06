# type: ignore
"""The characters' prompt segments drawn as bands at the bottom of the Dope Sheet (Timeline included) and the Graph
Editor, one band per character: the panel's character, then the other selected characters with segments.

The layout (where each band and segment is, in region pixels) is computed by plain functions, used both to draw and
to find what is under the mouse (segment_operators). Drawing only reads it.
"""
from dataclasses import dataclass, field

import bpy
from bpy.app.handlers import persistent

from . import segment_track
from .properties import is_scene_armature

# In pixels at UI scale 1
BAND_BOTTOM = 22.0  # above the horizontal scroll bar
BAND_HEIGHT = 34.0
BAND_GAP = 4.0
STRIPE = 3.0  # colour stripe on top of a segment
EDGE = 5.0  # a boundary can be grabbed this far on each side
ADD_GAP = 4.0  # the "+" button after the panel's character's track
ADD_WIDTH = 20.0
TAG_PADDING = 6.0
FONT = 11.0
TAG_FONT = 10.0
# The Graph Editor draws its value scale over the left of its main region: the name tags start after it
GRAPH_SCALE_WIDTH = 24.0

PALETTE = ((0.36, 0.55, 0.85), (0.85, 0.55, 0.30), (0.45, 0.72, 0.45), (0.70, 0.45, 0.80))

# What is under the mouse, set by the hover operator: (character name, segment index, part) or None
hover = None


@dataclass
class Bar:
    index: int
    x0: float
    x1: float


@dataclass
class Band:
    character: str
    target: bool  # the panel's character
    y0: float
    y1: float
    tag_x0: float = 0.0  # the character's name tag, over the left of the band
    tag_x1: float = 0.0
    add_x0: float = 0.0  # the "+" button adding a segment (the panel's character only; add_x0 == add_x1: none)
    add_x1: float = 0.0
    bars: list = field(default_factory=list)


def band_layout(characters, frame_to_x, ui_scale=1.0, tag_x0=0.0, tag_width=None):
    """[Band] for characters [(name, is the panel's character, [(start frame, end frame)])], bottom to top.
    frame_to_x: region x of a frame number (a float). A segment spans from half a frame before its start to half
    a frame after its end. tag_x0: left of the name tags; tag_width(name): their width (default: none)."""
    bands = []
    for row, (name, target, frames) in enumerate(characters):
        y0 = (BAND_BOTTOM + row * (BAND_HEIGHT + BAND_GAP)) * ui_scale
        width = tag_width(name) if tag_width is not None else 0.0
        band = Band(name, target, y0, y0 + BAND_HEIGHT * ui_scale, tag_x0, tag_x0 + width)
        for index, (start, end) in enumerate(frames):
            band.bars.append(Bar(index, frame_to_x(start - 0.5), frame_to_x(end + 0.5)))
        if target and band.bars:
            band.add_x0 = band.bars[-1].x1 + ADD_GAP * ui_scale
            band.add_x1 = band.add_x0 + ADD_WIDTH * ui_scale
        bands.append(band)
    return bands


def hit_test(bands, x, y, ui_scale=1.0):
    """(character, segment index, part) under the region point (x, y), or None. part: 'START' or 'END' near a
    boundary of the segment (EDGE pixels), else 'BODY'. Between two segments, the boundary belongs to the segment
    after it ('START'); the track's end is the last segment's 'END'. On the name tag: (character, None, 'TAG'); on
    the "+" button: (character, None, 'ADD')."""
    edge = EDGE * ui_scale
    for band in bands:
        if not band.y0 <= y <= band.y1 or not band.bars:
            continue
        if band.tag_x0 <= x <= band.tag_x1:
            return band.character, None, 'TAG'
        if band.add_x0 < band.add_x1 and band.add_x0 <= x <= band.add_x1:
            return band.character, None, 'ADD'
        last = band.bars[-1]
        for bar in band.bars:
            if abs(x - bar.x0) <= edge:
                return band.character, bar.index, 'START'
        if abs(x - last.x1) <= edge:
            return band.character, last.index, 'END'
        for bar in band.bars:
            if bar.x0 <= x <= bar.x1:
                return band.character, bar.index, 'BODY'
    return None


### What is shown

def shown_characters(context):
    """[(object, is the panel's character)]: the panel's character if it has segments, then the other selected
    armatures of the scene with segments, by name"""
    scene = context.scene
    if not getattr(scene, "retargetor_show_segments", True):
        return []
    target = scene.retargetor_target
    result = []
    if target is not None and is_scene_armature(scene, target) and len(target.retargetor.segments) > 0:
        result.append((target, True))
    others = [obj for obj in context.selected_objects
              if obj.type == 'ARMATURE' and obj != target and len(obj.retargetor.segments) > 0]
    result += [(obj, False) for obj in sorted(others, key=lambda o: o.name)]
    return result


def region_bands(context, region):
    """The bands of the shown characters in a region of an animation editor, and the objects"""
    shown = shown_characters(context)
    view = region.view2d
    ui_scale = context.preferences.system.ui_scale

    def frame_to_x(frame):
        return view.view_to_region(frame, 0.0, clip=False)[0]

    characters = [(obj.name, target, [(s.frame_start, s.frame_end) for s in obj.retargetor.segments])
                  for obj, target in shown]
    space = context.space_data
    tag_x0 = GRAPH_SCALE_WIDTH * ui_scale if space is not None and space.type == 'GRAPH_EDITOR' else 0.0
    font = TAG_FONT * ui_scale
    return band_layout(characters, frame_to_x, ui_scale, tag_x0,
                       lambda name: _text_width(name, font) + 2 * TAG_PADDING * ui_scale), shown


### Key poses, cached until an action changes

_key_frames_cache = {}


def key_frames(rig):
    """The character's key poses (frames), [] without a usable rig profile"""
    action = rig.animation_data.action if rig.animation_data else None
    key = (rig.name, action.name if action else "")
    if key not in _key_frames_cache:
        from . import generation
        from .segment_operators import character_profile
        frames = []
        rig_profile = character_profile(rig)
        if rig_profile is not None:
            try:
                frames = generation.find_key_frames(rig, rig_profile)
            except ValueError:
                pass
        _key_frames_cache[key] = frames
    return _key_frames_cache[key]


@persistent
def forget_key_frames(_scene, depsgraph):
    """An action changed (a key added, moved, retyped...): the key poses are read again on the next redraw"""
    if _key_frames_cache and any(isinstance(update.id, bpy.types.Action) for update in depsgraph.updates):
        _key_frames_cache.clear()


@persistent
def forget_all(_dummy=None):
    _key_frames_cache.clear()


### Drawing

def _shader():
    import gpu
    return gpu.shader.from_builtin('UNIFORM_COLOR')


def _tris(verts, indices, color):
    import gpu
    from gpu_extras.batch import batch_for_shader
    gpu.state.blend_set('ALPHA')  # blf resets it
    shader = _shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices).draw(shader)


def _rect(x0, y0, x1, y1, color):
    _tris([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [(0, 1, 2), (0, 2, 3)], color)


def _polygon(points, color):
    """A convex polygon"""
    if len(points) < 3:
        return
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    count = len(points)
    _tris([(cx, cy)] + points, [(0, 1 + i, 1 + (i + 1) % count) for i in range(count)], color)


def _outline(points, color, width):
    import math
    count = len(points)
    for i in range(count):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % count]
        length = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / length * width / 2, (bx - ax) / length * width / 2
        _tris([(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)],
              [(0, 1, 2), (0, 2, 3)], color)


def _rounded(x0, y0, x1, y1, radius, left=True, right=True):
    """Points of a rectangle, rounded on the left and / or right corners"""
    import math
    radius = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    points = []

    def arc(cx, cy, start):
        for k in range(6):
            angle = math.radians(start + 18 * k)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    if right:
        arc(x1 - radius, y0 + radius, 270)
        arc(x1 - radius, y1 - radius, 0)
    else:
        points += [(x1, y0), (x1, y1)]
    if left:
        arc(x0 + radius, y1 - radius, 90)
        arc(x0 + radius, y0 + radius, 180)
    else:
        points += [(x0, y1), (x0, y0)]
    return points


def _clip(points, x0, y0, x1, y1):
    """A convex polygon clipped to a rectangle (Sutherland-Hodgman)"""
    def cut(points, inside, cross):
        result = []
        for i in range(len(points)):
            a, b = points[i - 1], points[i]
            if inside(b):
                if not inside(a):
                    result.append(cross(a, b))
                result.append(b)
            elif inside(a):
                result.append(cross(a, b))
        return result

    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    for inside, cross in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                          (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not points:
            break
        points = cut(points, inside, cross)
    return points


def _hatch(x0, y0, x1, y1, color, step, width):
    height = y1 - y0
    x = x0 - height
    while x < x1:
        _polygon(_clip([(x, y0), (x + width, y0), (x + width + height, y1), (x + height, y1)], x0, y0, x1, y1), color)
        x += step


def _gradient(x0, y0, x1, y1, left_color, right_color):
    import gpu
    from gpu_extras.batch import batch_for_shader
    gpu.state.blend_set('ALPHA')
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                              "color": [left_color, right_color, right_color, left_color]},
                             indices=[(0, 1, 2), (0, 2, 3)])
    batch.draw(shader)


def _text(x, y, text, size, color, clip):
    import blf
    blf.size(0, size)
    blf.color(0, *color)
    blf.enable(0, blf.CLIPPING)
    blf.clipping(0, *clip)
    blf.position(0, x, y, 0)
    blf.draw(0, text)
    blf.disable(0, blf.CLIPPING)


def _text_width(text, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, text)[0]


def _scaled(color, factor, alpha):
    return (color[0] * factor, color[1] * factor, color[2] * factor, alpha)


def draw_bands():
    """Draw handler of the Dope Sheet and Graph Editor main regions"""
    import gpu
    context = bpy.context
    region = context.region
    if region is None or region.type != 'WINDOW':
        return
    bands, shown = region_bands(context, region)
    if not bands:
        return
    from .preferences import active_backend
    ui = context.preferences.system.ui_scale
    font = FONT * ui
    fps = segment_track.scene_fps(context.scene)
    caps = active_backend(context).capabilities
    transition = caps.transition_duration * fps if caps.prompt_segments else 0.0
    view = region.view2d
    width, height = region.width, region.height
    stripe = STRIPE * ui
    for band, (rig, target) in zip(bands, shown):
        if band.y1 > height:
            break
        state = rig.retargetor
        dim = 1.0 if target else 0.55
        tag_right = band.tag_x1
        count = len(band.bars)
        for bar, item in zip(band.bars, state.segments):
            x0, x1 = bar.x0, bar.x1
            if x1 < 0 or x0 > width:
                continue
            color = PALETTE[bar.index % len(PALETTE)]
            hovered = hover is not None and hover[0] == rig.name and hover[1] == bar.index
            outline = _rounded(x0 + 1, band.y0, x1 - 1, band.y1, 4 * ui, left=bar.index == 0,
                               right=bar.index == count - 1)
            _polygon(outline, _scaled(color, 0.65 if hovered else 0.55, 0.82 if target else 0.65))
            _polygon(_clip(outline, x0, band.y1 - stripe, x1, band.y1), _scaled(color, 1.0, dim))
            if bar.index > 0 and transition > 0.0:
                before = PALETTE[(bar.index - 1) % len(PALETTE)]
                xt = max(view.view_to_region(item.frame_start - 0.5 - transition, 0.0, clip=False)[0],
                         band.bars[bar.index - 1].x0)
                _gradient(xt, band.y0, x0, band.y1 - stripe, _scaled(before, 0.55, 0.0), _scaled(color, 0.9, 0.85 * dim))
                _gradient(xt, band.y1 - stripe, x0, band.y1, _scaled(before, 1.0, dim), _scaled(color, 1.0, dim))
            if bar.index > 0 and target:
                _rect(x0 - 0.5, band.y1, x0 + 0.5, height, (1.0, 1.0, 1.0, 0.15))
            status = segment_track.segment_state(item)
            if status != 'GENERATED':
                _hatch(x0 + 1, band.y0, x1 - 1, band.y1 - stripe, (0.0, 0.0, 0.0, 0.28), 8 * ui, 3 * ui)
            if target and bar.index == state.segments_active_index:
                _outline(outline, (1.0, 1.0, 1.0, 0.95), 1.5 * ui)
            elif hovered:
                _outline(outline, (1.0, 1.0, 1.0, 0.5), 1.0 * ui)
            text_x = max(x0 + 6 * ui, tag_right + 6 * ui)
            clip = (max(x0, tag_right) + 2, band.y0, x1 - 6 * ui, band.y1)
            prompt = item.prompt or "(no prompt)"
            _text(text_x, band.y0 + 17 * ui, prompt, font, (1.0, 1.0, 1.0, dim if item.prompt else 0.5 * dim), clip)
            info = f"{item.frame_start}–{item.frame_end}   seed {item.seed}"
            if status == 'MODIFIED':
                info += "   modified"
            elif status == 'NEW':
                info += "   not generated"
            info_color = (1.0, 1.0, 1.0, 0.55 * dim) if status == 'GENERATED' else (1.0, 0.8, 0.4, dim)
            _text(text_x, band.y0 + 5 * ui, info, font * 0.85, info_color, clip)
        # Key poses: small diamonds on the band's bottom edge
        size, lift = 4 * ui, 2 * ui
        first, last = state.segments[0].frame_start, state.segments[-1].frame_end
        for frame in key_frames(rig):
            if first <= frame <= last:
                x = view.view_to_region(frame, 0.0, clip=False)[0]
                diamond = [(x, band.y0 - size + lift), (x + size, band.y0 + lift), (x, band.y0 + size + lift),
                           (x - size, band.y0 + lift)]
                _polygon(diamond, (0.95, 0.95, 0.95, dim))
                _outline(diamond, (0.0, 0.0, 0.0, 0.8 * dim), 1.0)
        if band.add_x0 < band.add_x1 and band.add_x0 < width:
            add_hovered = hover is not None and hover[0] == rig.name and hover[2] == 'ADD'
            box = _rounded(band.add_x0, band.y0, band.add_x1, band.y1, 4 * ui)
            _polygon(box, (0.3, 0.3, 0.3, 0.95) if add_hovered else (0.18, 0.18, 0.18, 0.85))
            cx, cy, arm = (band.add_x0 + band.add_x1) / 2, (band.y0 + band.y1) / 2, 5 * ui
            _rect(cx - arm, cy - 0.75 * ui, cx + arm, cy + 0.75 * ui, (1.0, 1.0, 1.0, 0.8))
            _rect(cx - 0.75 * ui, cy - arm, cx + 0.75 * ui, cy + arm, (1.0, 1.0, 1.0, 0.8))
        # The character's name, held at the left edge
        tag_hovered = hover is not None and hover[0] == rig.name and hover[2] == 'TAG'
        _polygon(_rounded(band.tag_x0, band.y0, band.tag_x1, band.y1, 3 * ui, left=False),
                 (0.2, 0.2, 0.2, 0.95) if tag_hovered else (0.12, 0.12, 0.12, 0.92))
        if target:
            _rect(band.tag_x0, band.y0, band.tag_x0 + 3 * ui, band.y1, (1.0, 1.0, 1.0, 0.8))
        _text(band.tag_x0 + TAG_PADDING * ui, band.y0 + (BAND_HEIGHT * ui - TAG_FONT * ui * 0.7) / 2, rig.name,
              TAG_FONT * ui, (1.0, 1.0, 1.0, 0.9 if target else 0.6), (band.tag_x0, band.y0, band.tag_x1, band.y1))
    gpu.state.blend_set('NONE')


### Show / hide

def draw_view_menu(self, _context):
    self.layout.separator()
    self.layout.prop(_context.scene, "retargetor_show_segments")


_VIEW_MENUS = ("DOPESHEET_MT_view", "GRAPH_MT_view", "TIME_MT_view")
_handlers = []


def register():
    bpy.types.Scene.retargetor_show_segments = bpy.props.BoolProperty(
        name="Show Prompt Segments", default=True, update=lambda _self, _context: segment_track.tag_redraw(),
        description="Show the characters' prompt segments at the bottom of the animation editors (Retargetor)")
    for space in (bpy.types.SpaceDopeSheetEditor, bpy.types.SpaceGraphEditor):
        _handlers.append((space, space.draw_handler_add(draw_bands, (), 'WINDOW', 'POST_PIXEL')))
    for name in _VIEW_MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(draw_view_menu)
    bpy.app.handlers.depsgraph_update_post.append(forget_key_frames)
    bpy.app.handlers.load_post.append(forget_all)


def unregister():
    if forget_all in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(forget_all)
    if forget_key_frames in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(forget_key_frames)
    for name in _VIEW_MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.remove(draw_view_menu)
    for space, handler in _handlers:
        space.draw_handler_remove(handler, 'WINDOW')
    _handlers.clear()
    del bpy.types.Scene.retargetor_show_segments
