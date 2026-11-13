"""The ARDY backend's worker, run with the Python of ARDY's environment:
    <ardy env>/Scripts/python.exe -I -u worker.py --model ARDY-SOMA-RP-30FPS-Horizon60 --text-encoder INT8

ARDY generates autoregressively, one window (its horizon: 2 s) after the other, each one continuing the last
frames of the previous ones; the worker sends each window's frames as soon as it is done. As in ARDY's own demo:
- each window sees its history (HISTORY_SECONDS) and the key poses ahead of it, within a 10 s window;
- prompt segments: a window generates with the prompt of the segment it starts in, and stops at the segment's end;
  the next one starts there with the next prompt (the model makes the transition);
- the post-processing (feet, key poses hit exactly) runs on each window's new frames, and the next window continues
  the corrected motion.
The model is loaded once and kept loaded: about 15 s with a quantized text encoder (models.TEXT_ENCODERS), about a
minute with the full one (Llama 3 8B in bfloat16); a 5 s motion then takes about a second on an RTX 3090.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backends import protocol  # noqa: E402
from backends.ardy import models  # noqa: E402
from backends.shared import convert, messages  # noqa: E402

BACKEND_ID = "ardy"
LABEL = "ARDY"


class ArdyHandler:
    def __init__(self, model_name, text_encoder=models.DEFAULT_TEXT_ENCODER):
        self.model_name = model_name
        self.text_encoder = models.text_encoder(text_encoder)
        self.checkpoint = models.checkpoint(model_name)
        self.model = None
        self.postprocess = None
        self._layout = None
        self._skeleton = None
        self._skel = None   # ARDY's skeleton object

    def _model_skeleton(self):
        if self._skel is None:
            if self.model is not None:
                self._skel = self.model.skeleton
            elif self.checkpoint.skeleton == "soma":
                from ardy.skeleton import SOMASkeleton30
                self._skel = SOMASkeleton30()
            else:
                from ardy.skeleton import CoreSkeleton27
                self._skel = CoreSkeleton27()
        return self._skel

    def _skeleton_layout(self):
        if self._layout is None:
            skel = self._model_skeleton()
            model_names = list(skel.bone_order_names)
            right_hip, left_hip = skel.hip_joint_names
            # The output's skeleton: SOMA's 77 joints (relaxed hands), as Kimodo's; Core's own 27
            full = skel.somaskel77 if self.checkpoint.skeleton == "soma" else skel
            names = list(full.bone_order_names)
            parents = [int(p) for p in full.joint_parents.tolist()]
            neutral = full.neutral_joints.detach().cpu().numpy()
            self._layout = convert.ModelLayout(
                names=names, parents=parents, model_names=model_names, root=names[full.root_idx],
                right_hip=right_hip, left_hip=left_hip, neutral=neutral)
            # SOMA's rest hips height as Kimodo's armature; Core's neutral joints put the toes on the floor
            height = convert.HIPS_HEIGHT if self.checkpoint.skeleton == "soma" else float(-neutral[:, 1].min())
            self._skeleton = convert.skeleton_from(names, parents, neutral, height)
            if self._skeleton.root != models.ROOT_JOINT:
                raise RuntimeError(f"Unexpected root joint '{self._skeleton.root}'.")
        return self._layout

    def skeleton(self):
        self._skeleton_layout()
        return self._skeleton

    def load(self, context):
        if self.model is not None:
            return
        context.progress(0.0, messages.loading(LABEL))
        import torch
        from ardy.model import load_model
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            print(messages.no_cuda(LABEL), file=sys.stderr)
        if self.text_encoder.quantized:
            self.model = load_model(self.model_name, device=device, text_encoder=False)
            self.model.text_encoder = quantized_text_encoder(self.text_encoder, device)
        else:
            self.model = load_model(self.model_name, device=device)
        self._skel = self.model.skeleton
        fps = float(self.model.motion_rep.fps)
        if abs(fps - self.checkpoint.fps) > 1e-6 or int(self.model.gen_horizon_len) != self.checkpoint.horizon:
            raise RuntimeError(f"{self.model_name} runs at {fps} fps with a horizon of {self.model.gen_horizon_len} "
                               f"frames; the backend expects {self.checkpoint.fps} and {self.checkpoint.horizon}.")
        if int(self.model.num_frames_per_token) != models.TOKEN_FRAMES:
            raise RuntimeError(f"Unexpected token size: {self.model.num_frames_per_token} frames.")
        try:
            import motion_correction._motion_correction  # noqa: F401
            from ardy.postprocess import post_process_motion
            self.postprocess = post_process_motion
        except ImportError:
            print("ARDY's post-processing isn't installed: key poses are followed less exactly.", file=sys.stderr)

    def generate(self, request, context):
        layout = self._skeleton_layout()
        if self.model is None:
            self.load(context)
        import torch
        from ardy.tools import seed_everything

        checkpoint = self.checkpoint
        constraints, canonical, timing = convert.request_to_constraints(request, layout, checkpoint.fps,
                                                                        checkpoint.end_effectors)
        segments = request.segments or []
        if segments:
            counts = convert.segment_frame_counts(segments, timing, models.TOKEN_FRAMES - 1)
            ends = [sum(counts[:i + 1]) for i in range(len(counts))]
            prompts = [segment.prompt for segment in segments]
            seeds = [segment.seed for segment in segments]
        else:
            ends, prompts, seeds = [timing.count], [request.prompt], [request.seed]
        context.progress(0.02, messages.encoding(len(prompts)))
        features = [self._encode(prompt) for prompt in prompts]
        context.check_cancelled()

        stream = convert.FrameStream(canonical, request, timing)
        generator = WindowGenerator(self.model, checkpoint, constraints, self.postprocess, layout)
        segment = 0
        total = timing.count
        while generator.frames < total:
            while ends[segment] <= generator.frames:
                segment += 1
            if seeds[segment] is not None and generator.frames == (ends[segment - 1] if segment else 0):
                seed_everything(int(seeds[segment]))
            context.progress(0.05 + 0.9 * generator.frames / total,
                             messages.in_segment(messages.GENERATING, segment, len(ends)))
            stop = min(ends[segment], total)
            with torch.no_grad():
                rotations, roots = generator.next_window(features[segment], stop)
            context.check_cancelled()
            stream.add(rotations, roots)
            chunk = stream.ready(final=generator.frames >= total)
            if chunk is not None:
                context.send_frames(chunk[0], request.fps, chunk[1], chunk[2])
        print(f"Generated {total} model frames in {generator.windows} windows, heading {canonical.heading:.3f} rad",
              file=sys.stderr)

    def _encode(self, prompt):
        """The text features and padding mask of a prompt (an empty prompt: zero features, as ARDY does)"""
        return self.model._encode_text([sentence(prompt or "")])


class WindowGenerator:
    """ARDY's autoregressive generation, one window at a time (as its demo does: Ardy.autoregressive_step on the
    last frames generated, the key poses within the window as constraints, the post-processing on the new frames).
    frames: model frames generated so far (canonical frame, model axes)."""

    def __init__(self, model, checkpoint, constraints, postprocess, layout):
        self.model = model
        self.checkpoint = checkpoint
        # The request's constraints (dicts, shared.convert.request_to_constraints), on the whole motion's frames
        self.constraints = constraints
        self.postprocess = postprocess
        self.layout = layout
        self.motion = None   # normalized features of every frame so far (1, frames, D): the next window's history
        self.frames = 0
        self.windows = 0

    def _window_constraints(self, first, end, offset):
        """ARDY's constraint objects for the model frames first..end-1, their frames moved to offset + (frame -
        first) (the window's own frames)"""
        from ardy.constraints import load_constraints_lst
        return load_constraints_lst(window_constraints(self.constraints, first, end, offset), self.model.skeleton)

    def next_window(self, text, stop):
        """Generate the next window and keep its frames up to the model frame `stop` (excluded). Returns the kept
        frames' global rotations (n, joints, 3, 3) and root positions (n, 3) as numpy arrays, canonical frame."""
        import torch
        model = self.model
        rep = model.motion_rep
        device = model.device
        checkpoint = self.checkpoint
        token = models.TOKEN_FRAMES
        horizon = checkpoint.horizon
        start = self.frames
        history = 0 if self.motion is None else min(start, checkpoint.history_frames) // token * token
        first = start - history
        # The window: its history, the frames it generates and the key poses ahead, up to the model's window
        ahead = [i for c in self.constraints for i in c["frame_indices"] if i >= start]
        length = history + horizon
        if ahead:
            length = max(length, max(ahead) - first + 1)
        length = max(history + horizon, min(length, checkpoint.window_frames))
        length = math.ceil(length / token) * token
        window = self._window_constraints(start, first + length, history)
        motion_mask = observed = None
        if window:
            observed, motion_mask = rep.create_conditions_from_constraints(window, length=length, to_normalize=False,
                                                                          device=device)
            observed = rep.normalize(observed) * motion_mask
            observed[:history] = 0.0
            motion_mask[:history] = 0.0
            observed, motion_mask = observed[None], motion_mask[None]
        text_feat, text_mask = text
        zeros = torch.zeros(1, device=device)
        samples = model.autoregressive_step(
            num_frames=length, num_denoising_steps=models.DIFFUSION_STEPS, motion_mask=motion_mask,
            observed_motion=observed, cfg_weight=models.CFG_WEIGHT, text_feat=text_feat, text_pad_mask=text_mask,
            init_history_sequence=None if self.motion is None else self.motion[:, first:start],
            init_global_translation=None if self.motion is not None else torch.zeros(
                (1, rep.nfeats_dict[rep.root_pos_name]), device=device),
            init_first_heading_angle=None if self.motion is not None else zeros)
        keep = max(1, min(horizon, stop - start))
        new = slice(history, history + keep)
        unnormalized = rep.unnormalize(samples)
        output = rep.inverse(unnormalized, is_normalized=False)
        local = output["local_rot_mats"][:, new]
        roots = output["root_positions"][:, new]
        if self.postprocess is not None:
            kept = self._window_constraints(start, start + keep, 0)
            corrected = self.postprocess(local, roots, output["foot_contacts"][:, new], rep.skeleton,
                                         constraint_lst=kept or None)
            local, roots = corrected["local_rot_mats"], corrected["root_positions"]
            # The corrected frames back into features, for the next window's history; with the frame before them,
            # so their velocities are right
            before = 1 if history else 0
            if before + keep >= 2:
                span = slice(history - before, history + keep)
                features = rep(local_joint_rots=torch.cat((output["local_rot_mats"][:, span][:, :before], local), 1),
                               root_positions=torch.cat((output["root_positions"][:, span][:, :before], roots), 1),
                               to_normalize=False)
                samples = samples.clone()
                samples[:, new] = rep.normalize(features)[:, before:]
        kept_samples = samples[:, new]
        self.motion = kept_samples if self.motion is None else torch.cat((self.motion, kept_samples), dim=1)
        self.frames += keep
        self.windows += 1
        return self._globals(local, roots)

    def _globals(self, local, roots):
        """Global rotations of the output's skeleton (SOMA: 77 joints) and root positions, numpy, batch removed"""
        skel = self.model.skeleton
        if hasattr(skel, "output_to_SOMASkeleton77"):
            full = skel.output_to_SOMASkeleton77({"local_rot_mats": local, "root_positions": roots})
            global_rots, posed = full["global_rot_mats"], full["posed_joints"]
        else:
            global_rots, posed, _ = skel.fk(local, roots)
        root = self.layout.index(self.layout.root)
        return global_rots[0].detach().cpu().numpy(), posed[0, :, root].detach().cpu().numpy()


def window_constraints(constraints, first, end, offset=0):
    """The constraints (a list of dicts, shared.convert.request_to_constraints) on the model frames first..end-1,
    their frames moved to offset + (frame - first). No torch."""
    chosen = []
    for constraint in constraints:
        picks = [k for k, i in enumerate(constraint["frame_indices"]) if first <= i < end]
        if not picks:
            continue
        part = dict(constraint)
        part["frame_indices"] = [constraint["frame_indices"][k] - first + offset for k in picks]
        for key in ("local_joints_rot", "root_positions", "root_2d", "smooth_root_2d", "global_root_heading"):
            if key in constraint:
                part[key] = [constraint[key][k] for k in picks]
        chosen.append(part)
    return chosen


def quantized_text_encoder(encoder, device):
    """ARDY's text encoder from a merged, quantized build (models.TextEncoder), from the Hugging Face cache, called
    as ARDY calls its own (LLM2VecEncoder)"""
    from huggingface_hub import snapshot_download
    from ardy.model.llm2vec import LLM2Vec, LLM2VecEncoder
    folder = snapshot_download(encoder.repo_id, revision=encoder.revision, local_files_only=True)
    wrapper = LLM2VecEncoder.__new__(LLM2VecEncoder)
    wrapper.llm_dim = 4096
    wrapper.model = LLM2Vec.from_pretrained(folder, device_map={"": device})
    # LLM2Vec picks Llama 3's instruction template from the model's name, which transformers 5 doesn't save: without
    # it the features aren't the full encoder's
    wrapper.model.model.config._name_or_path = "meta-llama/Meta-Llama-3-8B-Instruct"
    wrapper.model.model = wrapper.model.model.eval()
    wrapper._device = device
    return wrapper


def sentence(prompt):
    prompt = prompt.strip()
    if prompt and not prompt.endswith("."):
        prompt += "."
    return prompt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=models.DEFAULT_MODEL)
    parser.add_argument("--text-encoder", default=models.DEFAULT_TEXT_ENCODER)
    args = parser.parse_args()
    protocol.WorkerLoop(BACKEND_ID, ArdyHandler(args.model, args.text_encoder)).run()


if __name__ == "__main__":
    main()
