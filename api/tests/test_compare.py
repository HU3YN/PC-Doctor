"""Build comparison: rank a run among runs of the same graphics card and game."""

from __future__ import annotations

import io
import zipfile

from pcdoctor_analysis import synth

from pcdoctor_api.services import compare


def variant(speed: float, gpu_temp_offset: float = 0.0, game: str = "") -> dict:
    """The "healthy" sample run, with frame times divided by `speed` (so FPS
    scales with it), a GPU temperature offset, and optionally another game."""
    source = zipfile.ZipFile(io.BytesIO(synth.build("healthy").zip_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "presentmon.csv":
                lines = data.decode().splitlines()
                header = lines[0].split(",")
                ms_columns = [i for i, c in enumerate(header) if c.startswith("Ms")]
                rows = [lines[0]]
                for line in lines[1:]:
                    cells = line.split(",")
                    for i in ms_columns:
                        if cells[i]:
                            cells[i] = f"{float(cells[i]) / speed:.4f}"
                    if game:
                        cells[0] = game
                    rows.append(",".join(cells))
                data = "\n".join(rows).encode()
            elif name == "sensors.csv":
                lines = data.decode().splitlines()
                at = lines[0].split(",").index("gpu_temp_c")
                rows = [lines[0]]
                for line in lines[1:]:
                    cells = line.split(",")
                    if cells[at]:
                        cells[at] = f"{float(cells[at]) + gpu_temp_offset:.1f}"
                    rows.append(",".join(cells))
                data = "\n".join(rows).encode()
            target.writestr(name, data)
    return {"file": ("run.zip", out.getvalue(), "application/zip")}


def upload(client, **kwargs) -> dict:
    sent = client.post("/api/runs", files=variant(**kwargs))
    assert sent.status_code == 201, sent.text
    return sent.json()["run"]


def test_nothing_is_shown_below_the_minimum(client):
    runs = [upload(client, speed=1 + i / 10) for i in range(compare.MIN_PEERS)]
    answer = client.get(f"/api/runs/{runs[0]['id']}/compare").json()
    # Four other runs: one short of the minimum.
    assert answer["groups"][0]["runs"] == compare.MIN_PEERS - 1
    assert answer["groups"][0]["metrics"] == []
    assert "Fewer than" in answer["reason"]


def test_a_run_is_ranked_among_its_peers(client):
    speeds = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    runs = [upload(client, speed=s, gpu_temp_offset=s * 10) for s in speeds]
    fastest = client.get(f"/api/runs/{runs[-1]['id']}/compare").json()
    # All these runs share a CPU too: one table, under the narrower title.
    assert [g["title"] for g in fastest["groups"]] == ["Same CPU, graphics card and game"]
    group = fastest["groups"][0]
    assert group["runs"] == 5
    by_key = {m["key"]: m for m in group["metrics"]}
    assert by_key["avg_fps"]["better_than_pct"] == 100 and by_key["avg_fps"]["peers"] == 5
    # It also runs the hottest GPU, and lower is better for temperatures.
    assert by_key["gpu_temp_peak"]["better_than_pct"] == 0
    slowest = client.get(f"/api/runs/{runs[0]['id']}/compare").json()
    assert {m["key"]: m for m in slowest["groups"][0]["metrics"]}["avg_fps"]["better_than_pct"] == 0
    middle = client.get(f"/api/runs/{runs[2]['id']}/compare").json()
    rank = {m["key"]: m for m in middle["groups"][0]["metrics"]}["avg_fps"]
    assert rank["better_than_pct"] == 40 and rank["q1"] < rank["median"] < rank["q3"]


def test_other_games_are_not_peers(client):
    runs = [upload(client, speed=1 + i / 10) for i in range(3)]
    for i in range(4):
        upload(client, speed=2 + i / 10, game="OtherGame.exe")
    answer = client.get(f"/api/runs/{runs[0]['id']}/compare").json()
    assert answer["groups"][0]["runs"] == 2


def test_the_comparison_is_master_only(client, guest):
    run = upload(client, speed=1.0)
    assert guest.get(f"/api/runs/{run['id']}/compare").status_code == 401
    assert client.get("/api/runs/nope/compare").status_code == 404
