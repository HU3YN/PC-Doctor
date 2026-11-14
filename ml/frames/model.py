"""A small 1-D convolutional network that reads a window of frame times.

Input: a batch of raw frame-time windows in milliseconds, shape (batch, frames).
Output: one number per window, a *logit*. ``sigmoid(logit)`` is the model's
probability that the window contains stutter.

Why a 1-D CNN: a stutter is a *local* pattern (one long frame, a short burst,
a repeating long-short rhythm). A convolution slides the same small detector
along the whole window, so it finds the pattern wherever it is. A global max
at the end asks "did any position fire?" - which is the question.
"""

from __future__ import annotations

import torch
from torch import nn

# 60 FPS. The absolute channel is centred here so its values stay near 0.
REFERENCE_MS = 1000.0 / 60.0


def normalise(frames_ms: torch.Tensor) -> torch.Tensor:
    """Turn raw frame times (batch, frames) into the model's input (batch, 2, frames).

    Channel 0 - *shape*: ``log(frame / median of the window)``. Divides out the
    frame rate, so a spike looks the same at 30 FPS and at 200 FPS. A frame
    twice the median is log(2) = 0.69, whatever the FPS.

    Channel 1 - *scale*: ``log(frame / 16.7 ms)``. The label has an absolute
    part (a stutter frame is at least 8 ms longer than normal), and channel 0
    alone has thrown the absolute size away. This channel gives it back.

    The log squeezes huge hitches (500 ms) and keeps small differences visible.
    It is done inside the model (not in the data loader) so that the exported
    ONNX file takes raw milliseconds too: callers cannot forget to normalise.
    """
    frames_ms = frames_ms.clamp(min=0.5)  # no log(0) from a broken capture
    # The median, written as "sort, take the middle" (the lower middle for an
    # even count, like torch.median). ONNX has no median operator, but it has
    # sorting (TopK), so this form exports cleanly.
    n = frames_ms.shape[1]
    median = torch.sort(frames_ms, dim=1).values[:, (n - 1) // 2 : (n - 1) // 2 + 1]
    shape = torch.log(frames_ms / median)
    scale = torch.log(frames_ms / REFERENCE_MS)
    return torch.stack([shape, scale], dim=1)


class FrameCNN(nn.Module):
    """Three convolution blocks, then global max and mean pooling, then one linear layer.

    About 8,000 weights (at width 32): small enough to train on a laptop CPU in minutes and
    to run in well under a millisecond per window.
    """

    def __init__(self, width: int = 32) -> None:
        super().__init__()
        half = width // 2
        self.features = nn.Sequential(
            # Block 1: 7 frames wide - sees a spike and its neighbours.
            nn.Conv1d(2, half, kernel_size=7, padding=3),
            nn.ReLU(),
            # Block 2: wider view; a burst or a long-short rhythm spans several frames.
            nn.Conv1d(half, width, kernel_size=5, padding=2),
            nn.ReLU(),
            # Max-pool halves the length but keeps the strongest response,
            # so a single long frame is not averaged away.
            nn.MaxPool1d(2),
            nn.Conv1d(width, width, kernel_size=5, padding=2),
            nn.ReLU(),
        )
        # Max pooling over time answers "was there a stutter anywhere?";
        # mean pooling adds "how much of the window looks like this?".
        self.head = nn.Linear(2 * width, 1)

    def forward(self, frames_ms: torch.Tensor) -> torch.Tensor:
        x = normalise(frames_ms)  # (batch, 2, frames)
        x = self.features(x)  # (batch, width, frames / 2)
        pooled = torch.cat([x.amax(dim=2), x.mean(dim=2)], dim=1)  # (batch, 2 * width)
        return self.head(pooled).squeeze(1)  # (batch,) logits


@torch.no_grad()
def predict_logits(model: nn.Module, frames_ms, batch_size: int = 1024):
    """Logits for every window in ``frames_ms`` (a NumPy array (N, frames)), as NumPy.

    ``no_grad`` tells PyTorch not to record the steps for training: faster, and
    less memory. ``model.eval()`` matters for layers that act differently while
    training (this network has none, but it is a good habit).
    """
    import numpy as np

    model.eval()
    out = []
    for start in range(0, len(frames_ms), batch_size):
        chunk = torch.as_tensor(frames_ms[start : start + batch_size], dtype=torch.float32)
        out.append(model(chunk).numpy())
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def predict_proba(model: nn.Module, frames_ms, batch_size: int = 1024):
    """Stutter probability (0..1) for every window: the sigmoid of the logit."""
    import numpy as np

    return 1.0 / (1.0 + np.exp(-predict_logits(model, frames_ms, batch_size)))


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def save(model: FrameCNN, path: str, width: int) -> None:
    """Save the weights and the one setting needed to rebuild the network."""
    torch.save({"width": width, "state_dict": model.state_dict()}, path)


def load(path: str) -> FrameCNN:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    model = FrameCNN(width=checkpoint["width"])
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model
