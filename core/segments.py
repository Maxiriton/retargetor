"""Prompt segments: a character's track of prompts, one after the other. No bpy.

A track is a list of PromptSegment, contiguous: each one starts on the frame after the previous one ends, so the
motion is never undefined between them. Blender frame numbers, ends included.

The editing functions take a track and return a new one (the input is left alone), always contiguous. They
keep every segment between min_frames and max_frames long (max_frames None: no limit), by clamping the move.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class PromptSegment:
    start_frame: int
    end_frame: int
    prompt: str = ""
    seed: int | None = None

    @property
    def frame_count(self):
        return self.end_frame - self.start_frame + 1

    def to_dict(self):
        return {"start_frame": self.start_frame, "end_frame": self.end_frame, "prompt": self.prompt,
                "seed": self.seed}

    @classmethod
    def from_dict(cls, data):
        seed = data.get("seed")
        return cls(int(data["start_frame"]), int(data["end_frame"]), str(data.get("prompt", "")),
                   int(seed) if seed is not None else None)


def check_track(segments):
    """Raises ValueError if the segments are empty, or don't follow each other frame after frame"""
    if not segments:
        raise ValueError("The track has no segment.")
    for i, segment in enumerate(segments):
        if segment.end_frame < segment.start_frame:
            raise ValueError(f"Segment {i + 1} ends (frame {segment.end_frame}) before it starts "
                             f"(frame {segment.start_frame}).")
        if i > 0 and segment.start_frame != segments[i - 1].end_frame + 1:
            raise ValueError(f"Segment {i + 1} starts on frame {segment.start_frame}, segment {i} ends on frame "
                             f"{segments[i - 1].end_frame}: the segments must follow each other.")


def track_range(segments):
    """(first frame, last frame) of a track"""
    return segments[0].start_frame, segments[-1].end_frame


def segment_at(segments, frame):
    """Index of the segment holding the frame, or None"""
    for i, segment in enumerate(segments):
        if segment.start_frame <= frame <= segment.end_frame:
            return i
    return None


def _copy(segments):
    return [replace(segment) for segment in segments]


def _clamp(value, low, high):
    return max(low, min(high, value))


def _length_limits(count, min_frames, max_frames):
    """(lowest, highest) change of a segment's length keeping it within the limits. A segment already outside them
    may stay as it is (a change of 0 is always allowed), but not get further out."""
    high = float("inf") if max_frames is None else max(0, max_frames - count)
    return min(0, min_frames - count), high


def move_boundary(segments, boundary, frame, min_frames=1, max_frames=None):
    """Move a boundary to start on `frame`. Boundary i is the start of segment i; boundary len(segments) is the
    track's end (frame is then the frame after it). The segments on each side adapt; the others don't move."""
    result = _copy(segments)
    count = len(result)
    if not 0 <= boundary <= count:
        raise IndexError(f"No boundary {boundary} in a track of {count} segments.")
    current = result[boundary].start_frame if boundary < count else result[-1].end_frame + 1
    low, high = float("-inf"), float("inf")
    if boundary > 0:  # the segment before grows by the move
        grow_low, grow_high = _length_limits(result[boundary - 1].frame_count, min_frames, max_frames)
        low, high = max(low, grow_low), min(high, grow_high)
    if boundary < count:  # the segment after shrinks by the move
        grow_low, grow_high = _length_limits(result[boundary].frame_count, min_frames, max_frames)
        low, high = max(low, -grow_high), min(high, -grow_low)
    delta = int(_clamp(frame - current, low, high))
    if boundary > 0:
        result[boundary - 1].end_frame += delta
    if boundary < count:
        result[boundary].start_frame += delta
    return result


def move_segment(segments, index, offset, min_frames=1, max_frames=None):
    """Move a segment by `offset` frames, both its boundaries: the segments on each side adapt (the first and the
    last segment move the track's start and end)."""
    result = _copy(segments)
    count = len(result)
    if not 0 <= index < count:
        raise IndexError(f"No segment {index} in a track of {count} segments.")
    low, high = float("-inf"), float("inf")
    if index > 0:  # the one before grows by the offset
        grow_low, grow_high = _length_limits(result[index - 1].frame_count, min_frames, max_frames)
        low, high = max(low, grow_low), min(high, grow_high)
    if index < count - 1:  # the one after shrinks by the offset
        grow_low, grow_high = _length_limits(result[index + 1].frame_count, min_frames, max_frames)
        low, high = max(low, -grow_high), min(high, -grow_low)
    delta = int(_clamp(offset, low, high))
    result[index].start_frame += delta
    result[index].end_frame += delta
    if index > 0:
        result[index - 1].end_frame += delta
    if index < count - 1:
        result[index + 1].start_frame += delta
    return result


def split(segments, index, frame, min_frames=1):
    """Cut a segment in two, the second part starting on `frame`; both keep its prompt and seed.
    Raises ValueError if a part would be shorter than min_frames."""
    segment = segments[index]
    if frame - segment.start_frame < min_frames or segment.end_frame - frame + 1 < min_frames:
        raise ValueError(f"Frame {frame} is too close to the ends of segment {index + 1} "
                         f"({segment.start_frame}-{segment.end_frame}) to cut it there.")
    result = _copy(segments)
    second = replace(segment, start_frame=frame)
    result[index].end_frame = frame - 1
    result.insert(index + 1, second)
    return result


def append(segments, frame_count, prompt="", seed=None, start_frame=None):
    """A segment added after the last one (or starting on start_frame on an empty track)"""
    result = _copy(segments)
    start = result[-1].end_frame + 1 if result else start_frame
    if start is None:
        raise ValueError("An empty track needs a start frame.")
    result.append(PromptSegment(start, start + frame_count - 1, prompt, seed))
    return result


def remove(segments, index):
    """Remove a segment; the one before takes its frames (the one after, for the first segment), so the track
    keeps its range. Removing the last remaining segment leaves an empty track."""
    result = _copy(segments)
    removed = result.pop(index)
    if not result:
        return result
    if index > 0:
        result[index - 1].end_frame = removed.end_frame
    else:
        result[0].start_frame = removed.start_frame
    return result
