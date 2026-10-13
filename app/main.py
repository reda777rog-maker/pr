"""Application web « Studio de films IA »."""

import os
import shutil
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import get_settings
from .pipeline import FilmRequest, JobManager

STATIC = Path(__file__).parent / "static"
DOWNLOADS = {"film.mp4": "video/mp4", "film.srt": "application/x-subrip"}


class FilmCreate(BaseModel):
    idea: str = Field(min_length=3, max_length=2000)
    style: str = Field(default="cinématique", max_length=120)
    num_scenes: int = Field(default=6, ge=2, le=12)
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2})$")
    aspect: Literal["16:9", "9:16"] = "16:9"
    visual_mode: Literal["local", "image", "video"] = "local"
    subtitles: bool = True


def create_app(manager: JobManager | None = None) -> FastAPI:
    settings = manager.settings if manager else get_settings()
    manager = manager or JobManager(settings)
    app = FastAPI(title="Studio de films IA")
    app.state.manager = manager

    def find(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Film introuvable")
        return job

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/config")
    def config():
        return {
            "claude_model": settings.claude_model,
            "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "replicate": settings.has_replicate,
        }

    @app.post("/api/films", status_code=202)
    def create_film(body: FilmCreate):
        if body.visual_mode != "local" and not settings.has_replicate:
            raise HTTPException(400, "Ajoutez REPLICATE_API_TOKEN pour utiliser les images ou vidéos IA.")
        return manager.submit(FilmRequest(**body.model_dump())).public()

    @app.get("/api/films")
    def list_films():
        return [job.public() for job in manager.list()]

    @app.get("/api/films/{job_id}")
    def get_film(job_id: str):
        return find(job_id).public()

    @app.delete("/api/films/{job_id}", status_code=204)
    def delete_film(job_id: str):
        job = find(job_id)
        if job.status not in ("done", "error"):
            raise HTTPException(409, "Ce film est encore en fabrication.")
        shutil.rmtree(manager.job_dir(job_id), ignore_errors=True)
        manager.jobs.pop(job_id, None)

    @app.get("/films/{job_id}/{name}", include_in_schema=False)
    def download(job_id: str, name: str):
        job = find(job_id)
        path = manager.job_dir(job_id) / name
        if name not in DOWNLOADS or job.status != "done" or not path.is_file():
            raise HTTPException(404, "Fichier introuvable")
        return FileResponse(path, media_type=DOWNLOADS[name], filename=f"{job_id}-{name}")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app

