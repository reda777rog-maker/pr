"""Génération des visuels de chaque plan.

Trois sources possibles :
- « local » : une illustration procédurale peinte à partir des couleurs et du décor du plan
  (gratuit, aucune clé nécessaire) ;
- « image » : une image générée par un modèle texte→image sur Replicate ;
- « video » : un clip généré par un modèle texte→vidéo sur Replicate.
"""

import hashlib
import math
import random
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

from .screenplay import Scene

REPLICATE_API = "https://api.replicate.com/v1"


class VisualError(RuntimeError):
    pass


# --------------------------------------------------------------------------- rendu local


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def scene_seed(scene: Scene) -> int:
    return int(hashlib.sha256(scene.visual_prompt.encode("utf-8")).hexdigest()[:8], 16)


def _terrain_kind(prompt: str) -> str:
    text = prompt.lower()
    keywords = {
        "city": ("city", "street", "building", "skyline", "town", "urban", "tower"),
        "sea": ("sea", "ocean", "wave", "beach", "shore", "lake", "water", "boat", "ship"),
        "forest": ("forest", "tree", "wood", "jungle", "garden", "park"),
        "space": ("space", "planet", "galaxy", "star field", "nebula", "orbit", "astronaut"),
    }
    for kind, words in keywords.items():
        if any(word in text for word in words):
            return kind
    return "mountains"


def gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    column = Image.new("RGB", (1, 256))
    for y in range(256):
        column.putpixel((0, y), mix(top, bottom, y / 255))
    return column.resize(size, Image.BICUBIC)


def _ridge(rng: random.Random, width: int, base_y: float, amplitude: float, step: int = 8) -> list:
    waves = [(rng.uniform(0.5, 3.0), rng.uniform(0, math.tau), rng.uniform(0.3, 1.0)) for _ in range(4)]
    points = []
    for x in range(0, width + step, step):
        u = x / width
        offset = sum(a * math.sin(u * f * math.tau + p) for f, p, a in waves) / 2.2
        points.append((x, base_y - offset * amplitude))
    return points


def local_artwork(scene: Scene, size: tuple[int, int]) -> Image.Image:
    """Peint une illustration stylisée du plan, déterministe pour un même prompt."""
    width, height = size
    rng = random.Random(scene_seed(scene))
    sky_top, sky_bottom, accent = (hex_to_rgb(c) for c in (scene.colors + scene.colors * 2)[:3])
    kind = _terrain_kind(scene.visual_prompt)
    if kind == "space":
        sky_top, sky_bottom = mix(sky_top, (0, 0, 0), 0.7), mix(sky_bottom, (0, 0, 0), 0.5)

    img = gradient(size, sky_top, sky_bottom).convert("RGBA")

    # Étoiles / poussières lumineuses.
    stars = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(stars)
    for _ in range(int(width * height / (2500 if kind == "space" else 9000))):
        x, y = rng.uniform(0, width), rng.uniform(0, height * 0.7)
        r = rng.uniform(0.6, 2.2)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randint(60, 200)))
    img.alpha_composite(stars)

    # Astre avec halo.
    cx, cy = rng.uniform(0.2, 0.8) * width, rng.uniform(0.15, 0.45) * height
    radius = rng.uniform(0.06, 0.12) * min(width, height) * (2.2 if kind == "space" else 1)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (cx - radius * 3, cy - radius * 3, cx + radius * 3, cy + radius * 3), fill=accent + (110,)
    )
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius * 1.4)))
    ImageDraw.Draw(img).ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius), fill=mix(accent, (255, 255, 255), 0.35) + (255,)
    )

    # Plans successifs du décor, du plus lointain au plus proche.
    layers = 4
    for i in range(layers):
        depth = i / (layers - 1)
        color = mix(mix(sky_bottom, accent, 0.25), (8, 8, 16), 0.35 + 0.55 * depth)
        # Fond transparent de la même teinte : le flou ne crée pas de liseré sombre.
        layer = Image.new("RGBA", size, color + (0,))
        draw = ImageDraw.Draw(layer)
        base_y = height * (0.55 + 0.12 * i)
        if kind == "city":
            x = -rng.uniform(0, 40)
            while x < width:
                w = rng.uniform(0.03, 0.08) * width
                h = rng.uniform(0.1, 0.35) * height * (1.2 - 0.2 * depth)
                draw.rectangle((x, base_y - h, x + w, height), fill=color + (255,))
                for wy in range(int(base_y - h + 10), int(base_y), 14):
                    for wx in range(int(x + 5), int(x + w - 5), 10):
                        if rng.random() < 0.25:
                            draw.rectangle((wx, wy, wx + 3, wy + 5), fill=mix(accent, (255, 240, 200), 0.5) + (200,))
                x += w + rng.uniform(0, 12)
        elif kind == "sea" and i >= 1:
            points = _ridge(rng, width, base_y + 0.05 * height, height * 0.02, step=4)
            draw.polygon(points + [(width, height), (0, height)], fill=mix(color, sky_bottom, 0.2) + (255,))
            for _ in range(40):
                x, y = rng.uniform(0, width), rng.uniform(base_y + 0.06 * height, height)
                w = rng.uniform(10, 60)
                draw.line((x, y, x + w, y), fill=mix(accent, (255, 255, 255), 0.4) + (70,), width=2)
        elif kind == "forest" and i >= 1:
            ridge = _ridge(rng, width, base_y, height * 0.04)
            draw.polygon(ridge + [(width, height), (0, height)], fill=color + (255,))
            for _ in range(int(14 + 10 * depth)):
                x = rng.uniform(0, width)
                h = rng.uniform(0.12, 0.3) * height * (0.6 + depth)
                w = h * rng.uniform(0.25, 0.4)
                ground = base_y + rng.uniform(-0.01, 0.03) * height
                draw.polygon([(x, ground - h), (x - w / 2, ground), (x + w / 2, ground)], fill=color + (255,))
        else:
            ridge = _ridge(rng, width, base_y, height * (0.18 - 0.03 * i))
            draw.polygon(ridge + [(width, height), (0, height)], fill=color + (255,))
        if depth < 1:
            layer = layer.filter(ImageFilter.GaussianBlur(2.5 * (1 - depth)))
        img.alpha_composite(layer)

    # Vignette.
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((-width * 0.15, -height * 0.2, width * 1.15, height * 1.2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(width, height) * 0.12))
    dark = Image.new("RGBA", size, (0, 0, 0, 255))
    img = Image.composite(img, dark, mask)
    return img.convert("RGB")


# --------------------------------------------------------------------------- Replicate


class ReplicateClient:
    def __init__(self, token: str, timeout_s: float = 900):
        if not token:
            raise VisualError("REPLICATE_API_TOKEN est requis pour les modes Images IA et Vidéo IA.")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.timeout_s = timeout_s

    def run(self, model: str, inputs: dict) -> str:
        """Lance un modèle et renvoie l'URL de la première sortie."""
        response = self.session.post(
            f"{REPLICATE_API}/models/{model}/predictions",
            json={"input": inputs},
            headers={"Prefer": "wait=60"},
            timeout=90,
        )
        if response.status_code >= 400:
            raise VisualError(f"Replicate a refusé la requête ({response.status_code}) : {response.text[:300]}")
        prediction = response.json()
        deadline = time.monotonic() + self.timeout_s
        while prediction.get("status") not in ("succeeded", "failed", "canceled"):
            if time.monotonic() > deadline:
                raise VisualError("La génération Replicate a dépassé le délai maximal.")
            time.sleep(3)
            poll = self.session.get(prediction["urls"]["get"], timeout=30)
            poll.raise_for_status()
            prediction = poll.json()
        if prediction["status"] != "succeeded":
            raise VisualError(f"La génération Replicate a échoué : {prediction.get('error')}")
        output = prediction.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if not isinstance(output, str):
            raise VisualError("Replicate n'a renvoyé aucun fichier.")
        return output

    def download(self, url: str, path: Path) -> Path:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        return path

    def image(self, model: str, prompt: str, aspect_ratio: str, path: Path) -> Path:
        url = self.run(model, {"prompt": prompt, "aspect_ratio": aspect_ratio, "output_format": "png"})
        return self.download(url, path)

    def video(self, model: str, prompt: str, path: Path) -> Path:
        return self.download(self.run(model, {"prompt": prompt}), path)
