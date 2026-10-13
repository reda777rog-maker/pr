from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app import editor
from app.config import Settings
from app.pipeline import END_S, TITLE_S, FilmRequest, JobManager
from app.screenplay import ScreenplayError, write_screenplay

from .conftest import fake_voice, fake_writer, make_screenplay, wait_for


def test_local_film_end_to_end(manager):
    job = manager.submit(FilmRequest(idea="Un robot jardinier", num_scenes=2))
    job = wait_for(manager, job.id)

    assert job.status == "done", job.error
    film = manager.job_dir(job.id) / "film.mp4"
    expected = TITLE_S + 2 * 4 + END_S
    assert abs(editor.probe_duration(film) - expected) < 0.5
    srt = (manager.job_dir(job.id) / "film.srt").read_text(encoding="utf-8")
    assert "un petit robot se réveille" in srt
    assert not list(manager.job_dir(job.id).glob("scene_*.mp4"))


def test_vertical_film_without_voice_or_subtitles(settings):
    def broken_voice(text, language, path):
        raise RuntimeError("pas de réseau")

    manager = JobManager(settings, screenplay_writer=fake_writer, synthesize=broken_voice)
    job = manager.submit(FilmRequest(idea="Un robot", num_scenes=2, aspect="9:16", subtitles=False))
    job = wait_for(manager, job.id)

    assert job.status == "done", job.error
    assert len(job.warnings) == 1 and "Voix off" in job.warnings[0]
    assert not (manager.job_dir(job.id) / "film.srt").exists()
    assert "subtitles_url" not in job.public()


class FakeReplicate:
    def __init__(self, token):
        pass

    def image(self, model, prompt, aspect_ratio, path: Path):
        Image.new("RGB", (512, 896) if aspect_ratio == "9:16" else (896, 512), (200, 80, 40)).save(path)
        return path

    def video(self, model, prompt, path: Path):
        if "forest" in prompt:
            raise RuntimeError("modèle saturé")
        editor.run_ffmpeg(["-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=1.5", str(path)])
        return path


@pytest.mark.parametrize("mode", ["image", "video"])
def test_replicate_modes(settings, mode):
    manager = JobManager(settings, screenplay_writer=fake_writer, synthesize=fake_voice, replicate_factory=FakeReplicate)
    job = wait_for(manager, manager.submit(FilmRequest(idea="Un robot", num_scenes=2, visual_mode=mode)).id)

    assert job.status == "done", job.error
    if mode == "video":
        # Le plan 2 (forêt) a échoué côté IA : on retombe sur l'illustration locale.
        assert any("Plan 2" in w for w in job.warnings)
    else:
        assert job.warnings == []


def test_history_survives_restart(manager, settings):
    job = wait_for(manager, manager.submit(FilmRequest(idea="Un robot", num_scenes=2)).id)
    reloaded = JobManager(settings, screenplay_writer=fake_writer, synthesize=fake_voice)
    assert reloaded.get(job.id).status == "done"
    assert reloaded.get(job.id).screenplay["title"] == "Le Dernier Jardin"


def test_job_dir_rejects_traversal(manager):
    with pytest.raises(KeyError):
        manager.job_dir("../../etc")


def test_subtitle_cues_cover_spoken_duration():
    cues = editor.subtitle_cues("Première phrase. Deuxième phrase un peu plus longue !", 2.0, 4.0)
    assert len(cues) == 2
    assert cues[0][0] == 2.0 and abs(cues[-1][1] - 6.0) < 1e-9


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_write_screenplay_normalizes_output():
    screenplay = make_screenplay(3)
    screenplay.scenes[0].duration_seconds = 60
    screenplay.scenes[1].colors = ["bleu", "#zzzzzz"]
    screenplay.language = "FR-fr"
    client, messages = fake_client(SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=screenplay))

    result = write_screenplay("idée", "anime", 2, "auto", "claude-opus-5-5", client=client)

    assert len(result.scenes) == 2
    assert result.scenes[0].duration_seconds == 10
    assert all(c.startswith("#") and len(c) == 7 for c in result.scenes[1].colors)
    assert result.language == "fr"
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert "exactement 2" in messages.kwargs["messages"][0]["content"]


def test_write_screenplay_reports_refusal():
    details = SimpleNamespace(explanation="contenu interdit")
    client, _ = fake_client(SimpleNamespace(stop_reason="refusal", stop_details=details, parsed_output=None))
    with pytest.raises(ScreenplayError, match="contenu interdit"):
        write_screenplay("idée", "anime", 2, "auto", "claude-opus-5-5", client=client)


def test_screenplay_error_is_reported_on_job(settings: Settings):
    def failing_writer(**kwargs):
        raise ScreenplayError("Claude a refusé d'écrire ce film.")

    manager = JobManager(settings, screenplay_writer=failing_writer, synthesize=fake_voice)
    job = wait_for(manager, manager.submit(FilmRequest(idea="Un robot")).id)
    assert job.status == "error" and "refusé" in job.error
