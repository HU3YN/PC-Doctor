"""Tests for model.py: shapes, the normalisation, and that a few steps of training learn."""

from __future__ import annotations

import numpy as np
import torch

import model as frame_model
from dataset import WINDOW, make_synthetic, to_windows


def test_shapes():
    net = frame_model.FrameCNN(width=8)
    x = torch.full((3, WINDOW), 16.7)
    assert frame_model.normalise(x).shape == (3, 2, WINDOW)
    assert net(x).shape == (3,)


def test_shape_channel_ignores_frame_rate_scale_channel_does_not():
    x = torch.rand(2, WINDOW) * 10 + 5
    a, b = frame_model.normalise(x), frame_model.normalise(x * 2)
    torch.testing.assert_close(a[:, 0], b[:, 0])  # log(frame / median): scale-free
    torch.testing.assert_close(b[:, 1] - a[:, 1], torch.full_like(a[:, 1], float(np.log(2))))


def test_median_matches_torch_median():
    x = torch.rand(4, WINDOW) * 30 + 1
    n = x.shape[1]
    ours = torch.sort(x, dim=1).values[:, (n - 1) // 2]
    torch.testing.assert_close(ours, x.median(dim=1).values)


def test_a_few_training_steps_lower_the_loss():
    torch.manual_seed(0)
    w = to_windows(make_synthetic(18, seed=0, n_frames=WINDOW))  # 18 windows
    x, y = torch.as_tensor(w.frames), torch.as_tensor(w.labels, dtype=torch.float32)
    net = frame_model.FrameCNN(width=8)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    optimiser = torch.optim.Adam(net.parameters(), lr=1e-2)
    with torch.no_grad():
        before = loss_fn(net(x), y).item()
    for _ in range(15):
        optimiser.zero_grad()
        loss = loss_fn(net(x), y)
        loss.backward()
        optimiser.step()
    with torch.no_grad():
        after = loss_fn(net(x), y).item()
    assert after < before


def test_save_load_round_trip(tmp_path):
    net = frame_model.FrameCNN(width=8)
    path = tmp_path / "m.pt"
    frame_model.save(net, str(path), width=8)
    again = frame_model.load(str(path))
    x = np.full((2, WINDOW), 16.7, dtype=np.float32)
    np.testing.assert_allclose(
        frame_model.predict_proba(net, x), frame_model.predict_proba(again, x)
    )
