import subprocess
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline import JobManager
from app.screenplay import Scene, Screenplay


def make_screenplay(num_scenes: int = 2, language: str = "fr") -> Screenplay:
    prompts = [
        ("a small robot gardener in an abandoned city street at dawn", "zoom_in"),
        ("the robot finds a glowing flower in a misty forest", "pan_left"),
        ("the robot watches the sea at sunset from a boat", "zoom_out"),
    ]
    return Screenplay(
        title="Le Dernier Jardin",
        logline="Un robot jardinier cherche la dernière fleur du monde.",
        language=language,
        style_prompt="soft pastel animation",
        scenes=[
            Scene(
                heading=f"Plan {i + 1}",
                narration="Dans la ville silencieuse, un petit robot se réveille. Il cherche encore la couleur.",
                visual_prompt=prompts[i % len(prompts)][0],
                camera=prompts[i % len(prompts)][1],
                colors=["#1d2b64", "#f8cdda", "#ffb347"],
                duration_seconds=4,
            )
            for i in range(num_scenes)
        ],
    )


def fake_writer(**kwargs) -> Screenplay:
    return make_screenplay(kwargs["num_scenes"])


def fake_voice(text: str, language: str, path: Path) -> Path:
    path = path.with_suffix(".m4a")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        claude_model="claude-opus-5-5",
        replicate_token="",
        replicate_image_model="owner/image",
        replicate_video_model="owner/video",
        films_dir=tmp_path / "films",
    )


@pytest.fixture
def manager(settings) -> JobManager:
    return JobManager(settings, screenplay_writer=fake_writer, synthesize=fake_voice)


def wait_for(manager: JobManager, job_id: str, timeout: float = 180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job.status in ("done", "error"):
            return job
        time.sleep(0.2)
    raise TimeoutError(job_id)
