import pytest
import torch

import model as led_model
from dataset import CLASSES, IMAGE_SIZE
from predict import NOT_SURE, decide


def test_output_has_one_score_per_class():
    net = led_model.LedNet()
    out = net(torch.rand(2, 3, IMAGE_SIZE, IMAGE_SIZE))
    assert out.shape == (2, len(CLASSES))


def test_model_is_small():
    assert led_model.count_parameters(led_model.LedNet()) < 100_000


def test_probabilities_sum_to_one():
    probs = led_model.predict_proba(led_model.LedNet(), torch.rand(3, 3, IMAGE_SIZE, IMAGE_SIZE))
    assert torch.allclose(probs.sum(1), torch.ones(3), atol=1e-5)


def test_save_and_load_round_trip(tmp_path):
    torch.manual_seed(0)
    net = led_model.LedNet().eval()
    led_model.save(net, tmp_path / "leds.pt")
    loaded, _ = led_model.load(tmp_path / "leds.pt")
    x = torch.rand(1, 3, IMAGE_SIZE, IMAGE_SIZE)
    assert torch.equal(net(x), loaded(x))


def test_load_refuses_other_classes(tmp_path):
    torch.save(
        {"state_dict": led_model.LedNet().state_dict(), "classes": ["a", "b"]}, tmp_path / "x.pt"
    )
    with pytest.raises(ValueError, match="classes"):
        led_model.load(tmp_path / "x.pt")


def test_below_threshold_says_not_sure_instead_of_guessing():
    probs = torch.tensor(
        [
            [0.02, 0.02, 0.92, 0.02, 0.02],  # confident: dram
            [0.10, 0.45, 0.35, 0.05, 0.05],  # top is cpu at 0.45: not sure
            [0.80, 0.05, 0.05, 0.05, 0.05],  # exactly at the threshold counts
        ]
    )
    sure, unsure, edge = decide(probs, threshold=0.8)
    assert (sure.answer, sure.noboot_code) == ("dram", "led_dram")
    assert unsure.answer == NOT_SURE and unsure.best_guess == "cpu" and unsure.noboot_code is None
    assert (edge.answer, edge.noboot_code) == ("none", None)
