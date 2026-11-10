"""The progress messages the workers send while loading and generating, worded the same for every model (no bpy).

Loading: "Loading <model>" until the model and its text encoder are both ready, then "Encoding the prompt",
"Generating" (and "Post-processing" for a model that does it after the whole motion); with prompt segments,
"Segment 2/3: generating".
"""
ENCODING = "Encoding the prompt"
ENCODING_SEVERAL = "Encoding the prompts"
GENERATING = "Generating"
POST_PROCESSING = "Post-processing"


def loading(label):
    return f"Loading {label}"


def encoding(count=1):
    return ENCODING_SEVERAL if count > 1 else ENCODING


def in_segment(message, index, count):
    """message for the index-th of count prompt segments (as it is with a single one)"""
    if count <= 1:
        return message
    return f"Segment {index + 1}/{count}: {message[:1].lower()}{message[1:]}"


def no_cuda(label):
    return f"No CUDA device: {label} runs on the CPU, very slowly."
