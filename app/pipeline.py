"""Chaîne de fabrication d'un film et suivi des tâches en arrière-plan."""

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

from PIL import Image

from . import editor, voice
from .config import Settings
from .screenplay import Scene, Screenplay, write_screenplay
from .visuals import ReplicateClient, hex_to_rgb, local_artwork, scene_seed

VisualMode = Literal["local", "image", "video"]
JOB_ID = re.compile(r"^[0-9a-f]{12}$")
TITLE_S, END_S = 3.5, 2.5


@dataclass
class FilmRequest:
    idea: str
    style: str = "cinématique"
    num_scenes: int = 6
    language: str = "auto"
    aspect: Literal["16:9", "9:16"] = "16:9"
    visual_mode: VisualMode = "local"
    subtitles: bool = True


@dataclass
class Job:
    id: str
    request: FilmRequest
    status: str = "queued"
    progress: float = 0.0
    message: str = "En attente…"
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    screenplay: dict | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def public(self) -> dict:
        data = asdict(self)
        if self.status == "done":
            data["video_url"] = f"/films/{self.id}/film.mp4"
            if self.request.subtitles:
                data["subtitles_url"] = f"/films/{self.id}/film.srt"
        return data


class JobManager:
    def __init__(
        self,
        settings: Settings,
        screenplay_writer: Callable[..., Screenplay] = write_screenplay,
        synthesize: Callable[[str, str, Path], Path] = voice.synthesize,
        replicate_factory: Callable[[str], ReplicateClient] = ReplicateClient,
    ):
        self.settings = settings
        self.write_screenplay = screenplay_writer
        self.synthesize = synthesize
        self.replicate_factory = replicate_factory
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="film")
        settings.films_dir.mkdir(parents=True, exist_ok=True)
        self._load_history()

    # ------------------------------------------------------------------ état

    def _load_history(self) -> None:
        for path in self.settings.films_dir.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["request"] = FilmRequest(**data["request"])
                job = Job(**data)
            except (ValueError, TypeError, KeyError):
                continue
            if job.status not in ("done", "error"):
                job.status, job.error = "error", "Le serveur a redémarré pendant la fabrication."
            self.jobs[job.id] = job

    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            raise KeyError(job_id)
        return self.settings.films_dir / job_id

    def _update(self, job: Job, **changes) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(job, key, value)
            data = asdict(job)
        path = self.job_dir(job.id) / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def submit(self, request: FilmRequest) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], request=request)
        self.job_dir(job.id).mkdir(parents=True)
        with self.lock:
            self.jobs[job.id] = job
        self._update(job)
        self.executor.submit(self._run, job)
        return job

    # ------------------------------------------------------------------ fabrication

    def _run(self, job: Job) -> None:
        try:
            self._make_film(job)
            self._update(job, status="done", progress=100.0, message="Film terminé !", finished_at=time.time())
        except Exception as exc:  # toute erreur est rapportée à l'interface
            self._update(job, status="error", error=str(exc), message="Échec de la fabrication", finished_at=time.time())

    def _make_film(self, job: Job) -> None:
        req, workdir = job.request, self.job_dir(job.id)
        size = editor.SIZES[req.aspect]

        self._update(job, status="writing", progress=3.0, message="Claude écrit le scénario…")
        screenplay = self.write_screenplay(
            idea=req.idea, style=req.style, num_scenes=req.num_scenes,
            language=req.language, model=self.settings.claude_model,
        )  # fmt: skip
        self._update(job, screenplay=screenplay.model_dump(), progress=15.0)

        self._update(job, status="visuals", message="Création des images de chaque plan…")
        artworks = self._make_visuals(job, screenplay, workdir, size)

        scene_files: list[Path] = []
        cues: list[tuple[float, float, str]] = []
        title_bg = artworks[0] if isinstance(artworks[0], Image.Image) else local_artwork(screenplay.scenes[0], size)
        title_path = workdir / "scene_00_title.mp4"
        editor.render_still_scene(
            editor.title_card(screenplay.title, screenplay.logline, title_bg, size),
            "static", TITLE_S, size, None, title_path,
        )  # fmt: skip
        scene_files.append(title_path)
        clock = TITLE_S

        total = len(screenplay.scenes)
        for index, (scene, visual) in enumerate(zip(screenplay.scenes, artworks), start=1):
            self._update(
                job, status="editing", progress=40.0 + 50.0 * (index - 1) / total,
                message=f"Voix off et montage du plan {index}/{total}…",
            )  # fmt: skip
            audio, spoken = self._narrate(job, scene, screenplay.language, workdir / f"voice_{index:02d}.mp3")
            duration = max(float(scene.duration_seconds), spoken + editor.VOICE_DELAY_S + 0.8)
            out = workdir / f"scene_{index:02d}.mp4"
            if isinstance(visual, Path):
                editor.render_video_scene(visual, duration, size, audio, out)
            else:
                editor.render_still_scene(
                    visual, scene.camera, duration, size, audio, out,
                    particles_seed=scene_seed(scene) if req.visual_mode == "local" else None,
                    particle_color=hex_to_rgb(scene.colors[-1]),
                )  # fmt: skip
            scene_files.append(out)
            cues += editor.subtitle_cues(
                scene.narration, clock + editor.VOICE_DELAY_S, spoken or duration - editor.VOICE_DELAY_S - 0.6
            )
            clock += duration

        end_path = workdir / "scene_99_end.mp4"
        end_title = editor.END_TITLES.get(screenplay.language, "The End")
        editor.render_still_scene(editor.title_card(end_title, "", title_bg, size), "static", END_S, size, None, end_path)
        scene_files.append(end_path)

        self._update(job, progress=93.0, message="Assemblage final du film…")
        srt = editor.write_srt(cues, workdir / "film.srt") if req.subtitles else None
        editor.assemble(scene_files, workdir / "film.mp4", srt)
        for path in scene_files:
            path.unlink(missing_ok=True)

    def _make_visuals(self, job: Job, screenplay: Screenplay, workdir: Path, size) -> list:
        """Renvoie, pour chaque plan, une image PIL ou le chemin d'un clip vidéo."""
        mode = job.request.visual_mode
        scenes = screenplay.scenes
        if mode == "local":
            return [local_artwork(scene, (round(size[0] * 1.3), round(size[1] * 1.3))) for scene in scenes]

        client = self.replicate_factory(self.settings.replicate_token)
        done = 0

        def generate(item: tuple[int, Scene]):
            nonlocal done
            index, scene = item
            prompt = f"{scene.visual_prompt}. {screenplay.style_prompt}"
            try:
                if mode == "video":
                    result = client.video(self.settings.replicate_video_model, prompt, workdir / f"clip_{index:02d}.mp4")
                else:
                    path = client.image(
                        self.settings.replicate_image_model, prompt, job.request.aspect, workdir / f"image_{index:02d}.png"
                    )
                    with Image.open(path) as img:
                        result = img.convert("RGB")
            except Exception as exc:
                job.warnings.append(f"Plan {index} : visuel IA indisponible ({exc}), illustration locale utilisée.")
                result = local_artwork(scene, size)
            with self.lock:
                done += 1
                job.message = f"Génération IA des plans : {done}/{len(scenes)}…"
                job.progress = 15.0 + 25.0 * done / len(scenes)
            return result

        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(generate, enumerate(scenes, start=1)))

    def _narrate(self, job: Job, scene: Scene, language: str, path: Path) -> tuple[Path | None, float]:
        try:
            audio = self.synthesize(scene.narration, language, path)
            return audio, editor.probe_duration(audio)
        except Exception as exc:
            if not any(w.startswith("Voix off") for w in job.warnings):
                job.warnings.append(f"Voix off indisponible ({exc}) : film sans narration audio.")
            return None, 0.0
