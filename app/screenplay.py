"""Écriture du scénario : Claude transforme une idée en film découpé en plans."""

from typing import Literal

import anthropic
from pydantic import BaseModel

CameraMove = Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "static"]


class Scene(BaseModel):
    heading: str
    narration: str
    visual_prompt: str
    camera: CameraMove
    colors: list[str]
    duration_seconds: int


class Screenplay(BaseModel):
    title: str
    logline: str
    language: str
    style_prompt: str
    scenes: list[Scene]


class ScreenplayError(RuntimeError):
    pass


SYSTEM_PROMPT = """Tu es un réalisateur et scénariste de courts-métrages. À partir d'une idée, \
tu écris un film court complet, découpé en plans, qui sera ensuite fabriqué entièrement par des \
outils automatiques : chaque plan devient une image ou un clip généré par IA, la narration est lue \
par une voix de synthèse, puis tout est monté bout à bout.

Écris donc pour ce mode de fabrication :
- Le film a un vrai arc narratif (accroche, développement, chute) et la narration de chaque plan \
s'enchaîne naturellement avec la suivante. Une à trois phrases par plan, faites pour être dites à voix haute.
- `visual_prompt` est rédigé en anglais et décrit uniquement ce que l'on voit : sujet, décor, \
lumière, cadrage. Chaque plan est généré séparément, sans mémoire des autres : redécris donc les \
personnages et les lieux récurrents avec les mêmes détails physiques à chaque fois. Pas de texte, \
de logo ni de sous-titre dans l'image.
- `style_prompt` (en anglais) fixe l'esthétique commune à tout le film ; il sera ajouté à chaque \
`visual_prompt`, inutile de le répéter dedans.
- `camera` choisit le mouvement de caméra du plan.
- `colors` donne trois couleurs hexadécimales (#RRGGBB) qui résument l'ambiance du plan.
- `duration_seconds` est compris entre 4 et 10.
- `language` est le code ISO 639-1 de la langue de la narration et du titre."""


def build_request(idea: str, style: str, num_scenes: int, language: str) -> str:
    lang = (
        "dans la même langue que l'idée"
        if language == "auto"
        else f"dans la langue de code ISO « {language} »"
    )
    return (
        f"Idée du film : {idea.strip()}\n\n"
        f"Style visuel souhaité : {style}\n"
        f"Nombre de plans : exactement {num_scenes}\n"
        f"Écris le titre et la narration {lang}."
    )


def write_screenplay(
    idea: str,
    style: str,
    num_scenes: int,
    language: str,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> Screenplay:
    client = client or anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_request(idea, style, num_scenes, language)}],
        output_format=Screenplay,
    )
    if response.stop_reason == "refusal":
        explanation = response.stop_details.explanation if response.stop_details else None
        raise ScreenplayError(f"Claude a refusé d'écrire ce film. {explanation or ''}".strip())
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise ScreenplayError("Le scénario est incomplet, réessayez avec moins de plans.")
    return _normalize(response.parsed_output, num_scenes)


def _normalize(screenplay: Screenplay, num_scenes: int) -> Screenplay:
    """Borne les valeurs que le rendu ne peut pas gérer telles quelles."""
    scenes = screenplay.scenes[:num_scenes]
    if not scenes:
        raise ScreenplayError("Le scénario ne contient aucun plan.")
    for scene in scenes:
        scene.duration_seconds = max(4, min(10, scene.duration_seconds))
        scene.colors = [c for c in scene.colors if _is_hex_color(c)][:3] or ["#1b1f3b", "#53354a", "#e84545"]
    screenplay.scenes = scenes
    screenplay.language = (screenplay.language or "fr").lower()[:2]
    return screenplay


def _is_hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True
