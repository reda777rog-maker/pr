"""Montage : mouvements de caméra, cartons, voix off, sous-titres et assemblage final (ffmpeg)."""

import json
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 24
FADE_S = 0.4
VOICE_DELAY_S = 0.4
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280)}

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
END_TITLES = {"fr": "Fin", "es": "Fin", "it": "Fine", "de": "Ende", "pt": "Fim", "ar": "النهاية"}


class EditorError(RuntimeError):
    pass


def run_ffmpeg(args: list[str], stdin=None, cwd: Path | None = None) -> subprocess.Popen | None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    if stdin is not None:
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise EditorError(f"ffmpeg a échoué : {result.stderr.strip()[-500:]}")
    return None


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise EditorError(f"Impossible de lire la durée de {path.name}")
    return float(json.loads(result.stdout)["format"]["duration"])


# --------------------------------------------------------------------------- images


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Redimensionne et recadre au centre pour remplir exactement `size`."""
    width, height = size
    scale = max(width / img.width, height / img.height)
    resized = img.convert("RGB").resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (resized.width - width) // 2, (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: float) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=fnt) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def title_card(title: str, subtitle: str, background: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    img = cover(background, size).filter(ImageFilter.GaussianBlur(min(size) * 0.02))
    img = Image.blend(img, Image.new("RGB", size, (0, 0, 0)), 0.45)
    draw = ImageDraw.Draw(img)
    title_font, sub_font = font(round(min(size) * 0.09)), font(round(min(size) * 0.035))
    title_lines = wrap(draw, title, title_font, width * 0.85)
    sub_lines = wrap(draw, subtitle, sub_font, width * 0.75) if subtitle else []
    line_h, sub_h = title_font.size * 1.2, sub_font.size * 1.45
    y = (height - len(title_lines) * line_h - len(sub_lines) * sub_h - (sub_h if sub_lines else 0)) / 2
    for line in title_lines:
        draw.text((width / 2, y), line, font=title_font, fill=(255, 255, 255), anchor="ma")
        y += line_h
    y += sub_h if sub_lines else 0
    for line in sub_lines:
        draw.text((width / 2, y), line, font=sub_font, fill=(225, 225, 235), anchor="ma")
        y += sub_h
    return img


# --------------------------------------------------------------------------- plans


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    mask: Image.Image


def _glow_sprite(radius: int) -> Image.Image:
    size = radius * 4
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((radius, radius, size - radius, size - radius), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius * 0.6))


def _camera_box(camera: str, t: float, src: tuple[int, int]) -> tuple[float, float, float, float]:
    """Zone de l'image source visible à l'instant t (0→1), pour un mouvement de caméra donné."""
    ease = t * t * (3 - 2 * t)
    src_w, src_h = src
    if camera == "zoom_in":
        zoom, cx = 1.0 + 0.18 * ease, 0.5
    elif camera == "zoom_out":
        zoom, cx = 1.18 - 0.18 * ease, 0.5
    elif camera in ("pan_left", "pan_right"):
        zoom = 1.15
        span = (1 - 1 / zoom) / 2
        cx = 0.5 + span * (1 - 2 * ease) * (1 if camera == "pan_left" else -1)
    else:
        zoom, cx = 1.03 + 0.04 * ease, 0.5
    box_w, box_h = src_w / zoom, src_h / zoom
    x0 = cx * src_w - box_w / 2
    y0 = (src_h - box_h) / 2
    return x0, y0, x0 + box_w, y0 + box_h


def _audio_input(audio: Path | None) -> list[str]:
    if audio is None:
        return ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    return ["-i", str(audio)]


def _scene_filters(duration: float, audio: Path | None) -> str:
    fade = f"fade=t=in:st=0:d={FADE_S},fade=t=out:st={duration - FADE_S:.3f}:d={FADE_S}"
    delay = round(VOICE_DELAY_S * 1000)
    voice = f"adelay={delay}|{delay}," if audio is not None else ""
    return (
        f"[0:v]{fade},format=yuv420p[v];"
        f"[1:a]aresample=44100,aformat=channel_layouts=stereo,{voice}apad[a]"
    )


def _encode_args(duration: float, out: Path) -> list[str]:
    return [
        "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        str(out),
    ]  # fmt: skip


def render_still_scene(
    image: Image.Image,
    camera: str,
    duration: float,
    size: tuple[int, int],
    audio: Path | None,
    out: Path,
    particles_seed: int | None = None,
    particle_color: tuple[int, int, int] = (255, 240, 210),
) -> Path:
    """Anime une image fixe (mouvement de caméra + poussières lumineuses) et ajoute le son."""
    width, height = size
    src = cover(image, (round(width * 1.3), round(height * 1.3)))
    frames = max(2, round(duration * FPS))

    particles: list[Particle] = []
    if particles_seed is not None:
        rng = random.Random(particles_seed)
        sprites = {radius: _glow_sprite(radius) for radius in (2, 3, 4, 6)}
        for _ in range(28):
            alpha = rng.randint(70, 170)
            particles.append(
                Particle(
                    x=rng.uniform(0, width), y=rng.uniform(0, height),
                    vx=rng.uniform(-12, 12), vy=rng.uniform(-22, -6),
                    mask=sprites[rng.choice((2, 3, 4, 6))].point(lambda v, a=alpha: v * a // 255),
                )
            )  # fmt: skip
    color_layer = Image.new("RGB", (32, 32), particle_color)

    proc = run_ffmpeg(
        [
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
            *_audio_input(audio),
            "-filter_complex", _scene_filters(duration, audio),
            *_encode_args(duration, out),
        ],
        stdin=True,
    )  # fmt: skip
    try:
        for index in range(frames):
            t = index / (frames - 1)
            frame = src.transform(size, Image.EXTENT, _camera_box(camera, t, src.size), Image.BILINEAR)
            seconds = index / FPS
            for p in particles:
                x = (p.x + p.vx * seconds) % (width + 40) - 20
                y = (p.y + p.vy * seconds) % (height + 40) - 20
                frame.paste(color_layer.crop((0, 0, *p.mask.size)), (round(x), round(y)), p.mask)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    stderr = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise EditorError(f"ffmpeg a échoué : {stderr.strip()[-500:]}")
    return out


def render_video_scene(src: Path, duration: float, size: tuple[int, int], audio: Path | None, out: Path) -> Path:
    """Adapte un clip généré (boucle, recadrage, cadence) à la durée et au format du film."""
    width, height = size
    reframe = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={FPS},setsar=1,"
    )
    filters = _scene_filters(duration, audio).replace("[0:v]", f"[0:v]{reframe}", 1)
    run_ffmpeg(
        [
            "-stream_loop", "-1", "-i", str(src),
            *_audio_input(audio),
            "-filter_complex", filters,
            *_encode_args(duration, out),
        ]
    )  # fmt: skip
    return out


# --------------------------------------------------------------------------- sous-titres et assemblage


def split_sentences(text: str, max_chars: int = 90) -> list[str]:
    chunks = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        words, current = sentence.split(), ""
        for word in words:
            if current and len(current) + len(word) + 1 > max_chars:
                chunks.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            chunks.append(current)
    return chunks


def subtitle_cues(text: str, start: float, duration: float) -> list[tuple[float, float, str]]:
    """Répartit le texte sur la durée de lecture, proportionnellement à la longueur des phrases."""
    chunks = split_sentences(text)
    total = sum(len(c) for c in chunks) or 1
    cues, t = [], start
    for chunk in chunks:
        length = duration * len(chunk) / total
        cues.append((t, t + length, chunk))
        t += length
    return cues


def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> Path:
    blocks = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def assemble(scene_files: list[Path], out: Path, srt: Path | None = None) -> Path:
    """Colle les plans bout à bout, puis incruste les sous-titres si demandé."""
    workdir = out.parent
    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in scene_files), encoding="utf-8")
    joined = workdir / "joined.mp4" if srt else out
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", concat_list.name, "-c", "copy", "-movflags", "+faststart", joined.name],
        cwd=workdir,
    )
    if srt:
        style = "FontName=DejaVu Sans,FontSize=15,Outline=1.2,Shadow=0,MarginV=24,BorderStyle=1"
        run_ffmpeg(
            [
                "-i", joined.name,
                "-vf", f"subtitles={srt.name}:force_style='{style}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy", "-movflags", "+faststart", out.name,
            ],
            cwd=workdir,
        )  # fmt: skip
        joined.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)
    return out
