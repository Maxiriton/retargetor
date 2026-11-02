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
from backends.kimodo import convert, joints  # noqa: E402

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
            self._layout = convert.SomaLayout(
                names77=names, parents77=parents, names30=list(skel30.bone_order_names),
                root=names[skel77.root_idx], right_hip=right_hip, left_hip=left_hip, neutral77=neutral)
            self._skeleton = convert.soma_skeleton(names, parents, neutral)
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
        import torch
        from kimodo import load_model
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            print("No CUDA device: Kimodo runs on the CPU, very slowly.", file=sys.stderr)
        self.model = load_model(self.model_name, device=device, default_family="Kimodo")
        if abs(float(self.model.fps) - joints.MODEL_FPS) > 1e-6:
            raise RuntimeError(f"The model runs at {self.model.fps} fps, the backend expects {joints.MODEL_FPS}.")

    def generate(self, request, context):
        layout = self._soma()
        if self.model is None:
            self.load(context)
        from kimodo.constraints import load_constraints_lst
        from kimodo.tools import seed_everything

        constraints, canonical, key_indices, num_frames = convert.request_to_constraints(
            request, layout, joints.MODEL_FPS)
        if request.seed is not None:
            seed_everything(int(request.seed))
        constraint_list = load_constraints_lst(constraints, self.model.skeleton)

        def progress_bar(steps):
            steps = list(steps)
            for i, step in enumerate(steps):
                # Raises Cancelled when the add-on cancels: the denoising loop stops there
                context.progress(0.05 + 0.9 * i / len(steps), "Denoising")
                yield step

        prompt = request.prompt.strip()
        if prompt and not prompt.endswith("."):
            prompt += "."  # as kimodo_gen does
        context.progress(0.02, "Encoding the prompt")
        output = self.model(prompt, num_frames, constraint_lst=constraint_list, num_denoising_steps=DIFFUSION_STEPS,
                            num_samples=1, post_processing=True, return_numpy=True, progress_bar=progress_bar)
        context.check_cancelled()

        root_index = layout.index(layout.root)
        rotations, positions = convert.output_to_blender(
            output["global_rot_mats"][0], output["posed_joints"][0][:, root_index], canonical, request, key_indices)
        context.send_frames(request.start_frame, request.fps, rotations, positions)
        print(f"Generated {num_frames} model frames, heading {canonical.heading:.3f} rad", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=joints.DEFAULT_MODEL)
    args = parser.parse_args()
    protocol.WorkerLoop(BACKEND_ID, KimodoHandler(args.model)).run()


if __name__ == "__main__":
    main()
