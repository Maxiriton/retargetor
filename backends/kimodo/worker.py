"""The Kimodo backend's worker, run with the Python of the Kimodo venv:
    <kimodo-venv>/Scripts/python.exe -I -u worker.py --model Kimodo-SOMA-RP-v1.1

The model is loaded once (on "load", or on the first generation) and kept loaded: the first generation takes
about 10 s more (text encoder), the next ones about 3 s on an RTX 3090. The SOMA skeleton is read from the
user's own Kimodo install, so no SOMA data ships with the add-on.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backends import protocol  # noqa: E402
from backends.kimodo import joints  # noqa: E402
from backends.shared import convert  # noqa: E402

BACKEND_ID = "kimodo"
DIFFUSION_STEPS = 100


class KimodoHandler:
    def __init__(self, model_name):
        self.model_name = model_name
        self.model = None
        self._layout = None
        self._skeleton = None

    def _soma(self):
        if self._layout is None:
            from kimodo.skeleton import SOMASkeleton30
            skel30 = SOMASkeleton30()
            skel77 = skel30.somaskel77
            names = list(skel77.bone_order_names)
            parents = [int(p) for p in skel77.joint_parents.tolist()]
            neutral = skel77.neutral_joints.detach().cpu().numpy()
            right_hip, left_hip = skel77.hip_joint_names
            self._layout = convert.ModelLayout(
                names=names, parents=parents, model_names=list(skel30.bone_order_names),
                root=names[skel77.root_idx], right_hip=right_hip, left_hip=left_hip, neutral=neutral)
            self._skeleton = convert.skeleton_from(names, parents, neutral)
            if self._skeleton.root != joints.ROOT_JOINT:
                raise RuntimeError(f"Unexpected SOMA root joint '{self._skeleton.root}'.")
        return self._layout

    def skeleton(self):
        self._soma()
        return self._skeleton

    def load(self, context):
        if self.model is not None:
            return
        context.progress(0.0, "Loading Kimodo")
        demo_without_viewer()
        import torch
        from kimodo import load_model
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            print("No CUDA device: Kimodo runs on the CPU, very slowly.", file=sys.stderr)
        self.model = load_model(self.model_name, device=device, default_family="Kimodo")
        # The fork's text encoder loads its weights on first use, from a folder baked into its source by its own
        # installer: point it to the folder the add-on downloaded them to
        folder = os.environ.get("KIMODO_TEXT_ENCODER_DIR", "")
        encoder = getattr(self.model, "text_encoder", None)
        if folder and os.path.isdir(folder) and hasattr(encoder, "custom_dir"):
            encoder.custom_dir = folder
        if abs(float(self.model.fps) - joints.MODEL_FPS) > 1e-6:
            raise RuntimeError(f"The model runs at {self.model.fps} fps, the backend expects {joints.MODEL_FPS}.")

    def _generate_segments(self, request, timing, constraint_list, context):
        """The request's prompt segments in one pass, with Kimodo's multi-prompt generation: one segment after the
        other, each one starting from the end of the previous one (its first TRANSITION_FRAMES constrained by it),
        the key poses cropped to each segment."""
        counts = convert.segment_frame_counts(request.segments, timing, joints.TRANSITION_FRAMES)
        seeds = [int(s.seed) if s.seed is not None else None for s in request.segments]
        count = len(counts)
        # Kimodo's multi-prompt doesn't pass a progress bar to each segment's denoising loop: the instance's _generate
        # gets one, telling which segment runs (and checking for a cancel at each step)
        original = self.model._generate
        calls = [0]

        def generate(*args, **kwargs):
            index = calls[0]
            calls[0] += 1

            def progress_bar(steps):
                steps = list(steps)
                for i, step in enumerate(steps):
                    fraction = (index + i / len(steps)) / count
                    context.progress(0.05 + 0.85 * fraction, f"Segment {index + 1}/{count}: denoising")
                    yield step
                context.progress(0.05 + 0.85 * (index + 1) / count, f"Segment {index + 1}/{count}: post-processing")

            kwargs["progress_bar"] = progress_bar
            return original(*args, **kwargs)

        self.model._generate = generate
        try:
            return self.model([sentence(s.prompt) for s in request.segments], counts, multi_prompt=True,
                              seeds=seeds, constraint_lst=constraint_list, num_denoising_steps=DIFFUSION_STEPS,
                              num_samples=1, post_processing=True, return_numpy=True,
                              num_transition_frames=joints.TRANSITION_FRAMES)
        finally:
            del self.model._generate

    def generate(self, request, context):
        layout = self._soma()
        if self.model is None:
            self.load(context)
        from kimodo.constraints import load_constraints_lst
        from kimodo.tools import seed_everything

        constraints, canonical, timing = convert.request_to_constraints(request, layout, joints.MODEL_FPS,
                                                                        joints.END_EFFECTORS)
        num_frames = timing.count
        seed = request.segments[0].seed if request.segments else request.seed
        if seed is not None:
            seed_everything(int(seed))
        constraint_list = load_constraints_lst(constraints, self.model.skeleton) if constraints else []

        def progress_bar(steps):
            steps = list(steps)
            for i, step in enumerate(steps):
                # Raises Cancelled when the add-on cancels: the denoising loop stops there
                context.progress(0.05 + 0.85 * i / len(steps), "Denoising")
                yield step
            # Kimodo asks for the next step once the denoising is over: its post-processing comes next
            context.progress(0.9, "Post-processing")

        context.progress(0.02, "Encoding the prompt")
        if request.segments:
            output = self._generate_segments(request, timing, constraint_list, context)
        else:
            output = self.model(sentence(request.prompt), num_frames, constraint_lst=constraint_list,
                                num_denoising_steps=DIFFUSION_STEPS, num_samples=1, post_processing=True,
                                return_numpy=True, progress_bar=progress_bar)
        context.check_cancelled()

        root_index = layout.index(layout.root)
        rotations, positions = convert.output_to_blender(
            output["global_rot_mats"][0], output["posed_joints"][0][:, root_index], canonical, request, timing)
        context.send_frames(request.start_frame, request.fps, rotations, positions)
        print(f"Generated {num_frames} model frames, heading {canonical.heading:.3f} rad", file=sys.stderr)


def demo_without_viewer():
    """The fork's text encoder imports Kimodo's demo memory manager (kimodo.demo.memory_manager: psutil and torch
    only). Imported the normal way, kimodo/demo/__init__.py would load the whole demo and its web viewer (viser),
    which the add-on doesn't install: the package is registered bare, so only the memory manager loads."""
    if "kimodo.demo" in sys.modules:
        return
    import importlib.machinery
    import importlib.util
    import types
    spec = importlib.util.find_spec("kimodo")
    if spec is None or not spec.origin:
        return
    folder = os.path.join(os.path.dirname(spec.origin), "demo")
    if not os.path.isfile(os.path.join(folder, "memory_manager.py")):
        return
    package = types.ModuleType("kimodo.demo")
    package.__spec__ = importlib.machinery.ModuleSpec("kimodo.demo", None, is_package=True)
    package.__spec__.submodule_search_locations = [folder]
    package.__path__ = [folder]
    package.__package__ = "kimodo.demo"
    sys.modules["kimodo.demo"] = package


def sentence(prompt):
    prompt = prompt.strip()
    if prompt and not prompt.endswith("."):
        prompt += "."  # as kimodo_gen does
    return prompt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=joints.DEFAULT_MODEL)
    args = parser.parse_args()
    protocol.WorkerLoop(BACKEND_ID, KimodoHandler(args.model)).run()


if __name__ == "__main__":
    main()
