"""Prompt segments (core.segments), in requests and backends. No Blender.

Run with Blender's Python (tests/run_tests.py does it), from the repository root:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.base import Backend, Capabilities  # noqa: E402
from core import segments as seg  # noqa: E402
from core.motion import GenerationRequest, Motion, Pose  # noqa: E402
from core.segments import PromptSegment  # noqa: E402


def track(*bounds):
    """Segments from (start, end) pairs, prompts "a", "b"..."""
    return [PromptSegment(s, e, chr(ord("a") + i), i) for i, (s, e) in enumerate(bounds)]


def bounds(segments):
    return [(s.start_frame, s.end_frame) for s in segments]


class TestTrack(unittest.TestCase):
    def test_check(self):
        seg.check_track(track((1, 10), (11, 30)))
        with self.assertRaises(ValueError):
            seg.check_track([])
        with self.assertRaises(ValueError):
            seg.check_track(track((1, 10), (12, 30)))  # gap
        with self.assertRaises(ValueError):
            seg.check_track(track((1, 10), (10, 30)))  # overlap
        with self.assertRaises(ValueError):
            seg.check_track(track((5, 4)))

    def test_segment_at(self):
        t = track((1, 10), (11, 30))
        self.assertEqual(seg.segment_at(t, 1), 0)
        self.assertEqual(seg.segment_at(t, 11), 1)
        self.assertIsNone(seg.segment_at(t, 31))
        self.assertEqual(seg.track_range(t), (1, 30))

    def test_round_trip(self):
        s = PromptSegment(3, 40, "walks", 7)
        self.assertEqual(PromptSegment.from_dict(s.to_dict()), s)
        self.assertEqual(s.frame_count, 38)


class TestEditing(unittest.TestCase):
    def test_move_boundary(self):
        t = track((1, 10), (11, 30), (31, 40))
        self.assertEqual(bounds(seg.move_boundary(t, 1, 15)), [(1, 14), (15, 30), (31, 40)])
        self.assertEqual(bounds(t), [(1, 10), (11, 30), (31, 40)])  # input untouched
        # Clamped by the shrinking neighbour's minimum, and by the growing one's maximum
        self.assertEqual(bounds(seg.move_boundary(t, 1, 29, min_frames=5)), [(1, 25), (26, 30), (31, 40)])
        self.assertEqual(bounds(seg.move_boundary(t, 1, 29, max_frames=12)), [(1, 12), (13, 30), (31, 40)])
        # Track start and end move one segment only
        self.assertEqual(bounds(seg.move_boundary(t, 0, -4)), [(-4, 10), (11, 30), (31, 40)])
        self.assertEqual(bounds(seg.move_boundary(t, 3, 51)), [(1, 10), (11, 30), (31, 50)])
        self.assertEqual(bounds(seg.move_boundary(t, 3, 20, min_frames=3)), [(1, 10), (11, 30), (31, 33)])
        with self.assertRaises(IndexError):
            seg.move_boundary(t, 4, 50)

    def test_move_segment(self):
        t = track((1, 10), (11, 30), (31, 40))
        self.assertEqual(bounds(seg.move_segment(t, 1, 3)), [(1, 13), (14, 33), (34, 40)])
        self.assertEqual(bounds(seg.move_segment(t, 1, 20, min_frames=2)), [(1, 18), (19, 38), (39, 40)])
        self.assertEqual(bounds(seg.move_segment(t, 1, -20)), [(1, 1), (2, 21), (22, 40)])
        # The first one moves the track's start, the only one the whole track
        self.assertEqual(bounds(seg.move_segment(t, 0, -5)), [(-4, 5), (6, 30), (31, 40)])
        self.assertEqual(bounds(seg.move_segment(track((1, 10)), 0, 100)), [(101, 110)])

    def test_split(self):
        t = track((1, 10), (11, 30))
        result = seg.split(t, 1, 20)
        self.assertEqual(bounds(result), [(1, 10), (11, 19), (20, 30)])
        self.assertEqual([s.prompt for s in result], ["a", "b", "b"])
        with self.assertRaises(ValueError):
            seg.split(t, 1, 11)
        with self.assertRaises(ValueError):
            seg.split(t, 1, 29, min_frames=3)

    def test_append_remove(self):
        t = seg.append([], 10, "first", 1, start_frame=5)
        t = seg.append(t, 20, "second", 2)
        self.assertEqual(bounds(t), [(5, 14), (15, 34)])
        with self.assertRaises(ValueError):
            seg.append([], 10)
        t = seg.append(t, 6)
        self.assertEqual(bounds(seg.remove(t, 1)), [(5, 34), (35, 40)])  # the one before takes its frames
        self.assertEqual(bounds(seg.remove(t, 0)), [(5, 34), (35, 40)])  # the one after, for the first
        self.assertEqual([s.prompt for s in seg.remove(t, 0)], ["second", ""])
        self.assertEqual(seg.remove(track((1, 10)), 0), [])


class TestRequests(unittest.TestCase):
    def test_request_segments(self):
        pose = Pose({"root": (1.0, 0.0, 0.0, 0.0)}, (0.0, 0.0, 1.0))
        request = GenerationRequest(1, 40, 24.0, {1: pose}, segments=track((1, 10), (11, 40)))
        again = GenerationRequest.from_dict(request.to_dict())
        self.assertEqual(again.segments, request.segments)
        self.assertEqual(GenerationRequest.from_dict(GenerationRequest(1, 40, 24.0).to_dict()).segments, [])
        with self.assertRaises(ValueError):
            GenerationRequest(1, 50, 24.0, segments=track((1, 10), (11, 40)))
        with self.assertRaises(ValueError):
            GenerationRequest(1, 40, 24.0, segments=track((1, 10), (12, 40)))

    def test_backend_checks(self):
        class OnePass(Backend):
            label = "One pass"
            capabilities = Capabilities(prompt=True, prompt_segments=True, max_duration=10.0, min_key_poses=0)

        class EachSegment(Backend):
            label = "Each segment"
            capabilities = Capabilities(max_duration=10.0, min_key_poses=2)

        t = track((1, 240), (241, 480))  # 2 x 10 s at 24 fps: 20 s in all
        self.assertEqual(OnePass().segments_problem(t, 24.0, []), "")
        self.assertIn("Segment 2", OnePass().segments_problem(track((1, 240), (241, 481)), 24.0, []))
        self.assertIn("segment 1", EachSegment().segments_problem(t, 24.0, [1, 300, 480]))
        self.assertEqual(EachSegment().segments_problem(t, 24.0, [1, 240, 300, 480]), "")
        request = GenerationRequest(1, 480, 24.0, segments=t)
        OnePass().check_request(request)
        with self.assertRaises(ValueError):
            EachSegment().check_request(request)

    def test_request_context(self):
        """The motion around a regenerated segment: next to the range, checked, sent, refused by a backend that
        doesn't continue it"""
        pose = Pose({"root": (1.0, 0.0, 0.0, 0.0)}, (0.0, 0.0, 1.0))
        before = Motion(24.0, 6, [pose] * 5)  # frames 6-10
        after = Motion(24.0, 41, [pose] * 5)
        request = GenerationRequest(11, 40, 24.0, {20: pose}, context_before=before, context_after=after)
        again = GenerationRequest.from_dict(request.to_dict())
        self.assertEqual((again.context_before.start_frame, again.context_before.end_frame), (6, 10))
        self.assertEqual((again.context_after.start_frame, len(again.context_after.poses)), (41, 5))
        self.assertIsNone(GenerationRequest.from_dict(GenerationRequest(1, 40, 24.0).to_dict()).context_before)
        with self.assertRaisesRegex(ValueError, "end on frame 11"):
            GenerationRequest(12, 40, 24.0, context_before=before)
        with self.assertRaisesRegex(ValueError, "start on frame 40"):
            GenerationRequest(11, 39, 24.0, context_after=after)
        with self.assertRaisesRegex(ValueError, "fps"):
            GenerationRequest(11, 40, 25.0, context_before=before)

        class Continuing(Backend):
            label = "Continuing"
            capabilities = Capabilities(max_duration=10.0, min_key_poses=2, motion_context=True,
                                        context_duration=4 / 30)

        class Plain(Backend):
            label = "Plain"
            capabilities = Capabilities(max_duration=10.0, min_key_poses=2)

        self.assertEqual(Continuing().context_frame_count(30.0), 5)
        self.assertEqual(Continuing().context_frame_count(24.0), 5)  # 4 frames span 0.125 s < 4/30 s
        self.assertEqual(Plain().context_frame_count(30.0), 0)
        Continuing().check_request(request)  # one key pose and the motion on both sides
        with self.assertRaisesRegex(ValueError, "around"):
            Plain().check_request(request)
        segment = PromptSegment(11, 40)
        self.assertIn("at least 2", Continuing().segment_problem(segment, 24.0, [], before=True))
        self.assertEqual(Continuing().segment_problem(segment, 24.0, [], before=True, after=True), "")
        # Without context, a segment after another one is generated from that one's last frame
        self.assertEqual(Plain().segment_problem(segment, 24.0, [10, 20], before=True), "")
        self.assertIn("at least 2", Plain().segment_problem(segment, 24.0, [10, 20]))
        self.assertIn("at most 10", Plain().segment_problem(PromptSegment(1, 241), 24.0, [1, 241]))


if __name__ == "__main__":
    unittest.main()
