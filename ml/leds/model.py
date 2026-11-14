"""A small CNN, trained from scratch (no pretrained weights).

Three conv blocks, then a 4x4 average pool that keeps rough position (which
LED in the row is lit matters), then one linear layer to the five classes.
About 17 thousand weights - small enough to train on a CPU in minutes.
"""

from __future__ import annotations

import torch
from torch import nn

from dataset import CLASSES


def _block(c_in: int, c_out: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(c_in, c_out, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(c_out),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class LedNet(nn.Module):
    def __init__(self, n_classes: int = len(CLASSES), width: int = 16, dropout: float = 0.2):
        super().__init__()
        self.features = nn.Sequential(
            _block(3, width), _block(width, width * 2), _block(width * 2, width * 2)
        )
        self.pool = nn.AdaptiveAvgPool2d(4)
        self.head = nn.Sequential(
            nn.Flatten(), nn.Dropout(dropout), nn.Linear(width * 2 * 16, n_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.pool(self.features(x)))


DEFAULT_THREADS = 2  # the machines this runs on are shared; do not take every core


def limit_threads(threads: int = DEFAULT_THREADS) -> None:
    """Cap the CPU threads torch uses (call before any work)."""
    torch.set_num_threads(max(1, threads))


def count_parameters(net: nn.Module) -> int:
    return sum(p.numel() for p in net.parameters())


@torch.no_grad()
def predict_proba(net: nn.Module, images: torch.Tensor, batch_size: int = 64) -> torch.Tensor:
    """Softmax probabilities, shape (N, n_classes)."""
    net.eval()
    out = [
        torch.softmax(net(images[i : i + batch_size]), dim=1)
        for i in range(0, len(images), batch_size)
    ]
    return torch.cat(out) if out else torch.empty(0, len(CLASSES))


def save(net: LedNet, path, extra: dict | None = None) -> None:
    torch.save({"state_dict": net.state_dict(), "classes": list(CLASSES), **(extra or {})}, path)


def load(path) -> tuple[LedNet, dict]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("classes") != list(CLASSES):
        raise ValueError(
            f"{path} was trained on classes {checkpoint.get('classes')}, not {CLASSES}"
        )
    net = LedNet()
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()
    return net, checkpoint
