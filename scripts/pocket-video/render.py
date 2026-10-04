#!/usr/bin/env python3
"""Assemble the Aegis Pocket demo video from frames captured by drive.py.

    uv run --no-project --with pillow python render.py --build <dir> --out-dir docs/video
    uv run --no-project --with pillow python render.py --build <scratch> --out-dir <scratch>/out --placeholder

Each captured phone frame is composited onto a 1920x1080 dark branded background (phone frame
centred, beat title on the left, factual caption on the right, footer label), title and end cards
are drawn with Pillow, and ffmpeg encodes the timed stills to H.264 (30 fps, yuv420p, silent AAC
track), under 58 s. --placeholder first writes fake phone frames and a capture.json so the whole
assembly can be tested without a device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1920, 1080
FPS = 30
MAX_TOTAL = 57.5
XFADE = 0.3          # crossfade between beats (seconds)
XFADE_STEPS = 6
PHONE_H = 944

BG = (11, 15, 23)
BG2 = (19, 26, 42)
TEXT = (230, 237, 247)
DIM = (150, 163, 186)
FAINT = (98, 112, 138)
ACCENT = (79, 140, 255)
VIOLET = (167, 139, 250)
WARN = (245, 181, 68)

FONT_SANS = "/System/Library/Fonts/Avenir Next.ttc"      # 0 Bold, 2 Demi Bold, 5 Medium, 7 Regular
FONT_MONO = "/System/Library/Fonts/Menlo.ttc"
FALLBACK = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, weight: str = "regular", mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        try:
            return ImageFont.truetype(FONT_MONO, size, index=1 if weight == "bold" else 0)
        except OSError:
            pass
    idx = {"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight]
    try:
        return ImageFont.truetype(FONT_SANS, size, index=idx)
    except OSError:
        try:
            return ImageFont.truetype(FALLBACK, size, index={"bold": 1, "demi": 1, "medium": 10, "regular": 0}[weight])
        except OSError:
            return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=f) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def draw_lines(draw: ImageDraw.ImageDraw, xy: tuple[int, int], lines: list[str], f, fill, spacing: float = 1.3,
               anchor_center: bool = False) -> int:
    x, y = xy
    step = int(f.size * spacing)
    for ln in lines:
        if anchor_center:
            draw.text((x, y), ln, font=f, fill=fill, anchor="ma")
        else:
            draw.text((x, y), ln, font=f, fill=fill)
        y += step
    return y


def background() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    px = ImageDraw.Draw(img)
    for y in range(H):  # vertical gradient
        t = y / H
        c = tuple(int(BG[i] * (1 - t) + BG2[i] * t) for i in range(3))
        px.line([(0, y), (W, y)], fill=c)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([W // 2 - 520, H // 2 - 420, W // 2 + 520, H // 2 + 420], fill=(24, 44, 96))
    g.ellipse([W - 520, -260, W + 260, 420], fill=(46, 30, 92))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, Image.composite(glow, img, Image.new("L", (W, H), 255)), 0.55)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


class Phone:
    """Pastes a phone screenshot with bezel and shadow; geometry is fixed by the first frame."""

    def __init__(self, sample: Image.Image, height: int = PHONE_H) -> None:
        sw, sh = sample.size
        self.h = height
        self.w = int(round(sw * height / sh))
        self.r = int(self.w * 0.075)
        self.bezel = 12
        self.mask = rounded_mask((self.w, self.h), self.r)

    def paste(self, canvas: Image.Image, shot: Image.Image, cx: int, cy: int) -> None:
        b = self.bezel
        ow, oh = self.w + 2 * b, self.h + 2 * b
        x0, y0 = cx - ow // 2, cy - oh // 2
        shadow = Image.new("L", (ow + 160, oh + 160), 0)
        ImageDraw.Draw(shadow).rounded_rectangle([80, 100, 80 + ow, 100 + oh], radius=self.r + b, fill=170)
        shadow = shadow.filter(ImageFilter.GaussianBlur(36))
        canvas.paste((0, 0, 0), (x0 - 80, y0 - 80), shadow)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([x0, y0, x0 + ow, y0 + oh], radius=self.r + b, fill=(6, 8, 12), outline=(52, 64, 88), width=2)
        screen = shot.convert("RGB").resize((self.w, self.h), Image.LANCZOS)
        canvas.paste(screen, (x0 + b, y0 + b), self.mask)


def chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fg, bg) -> None:
    f = font(24, "demi")
    x, y = xy
    tw = draw.textlength(text, font=f)
    draw.rounded_rectangle([x, y, x + tw + 36, y + 46], radius=23, fill=bg, outline=fg, width=2)
    draw.text((x + 18, y + 9), text, font=f, fill=fg)


def compose_beat(base: Image.Image, phone: Phone, shot: Image.Image, beat: dict, n: int, total: int,
                 footer: str) -> Image.Image:
    img = base.copy()
    phone.paste(img, shot, W // 2, H // 2 + 6)
    d = ImageDraw.Draw(img)
    d.text((110, 64), "AEGIS POCKET", font=font(26, "demi"), fill=DIM)
    # Left: step + title + chip
    lx, colw = 110, 560
    d.text((lx, 330), f"{n:02d} / {total:02d}", font=font(30, "bold", mono=True), fill=ACCENT)
    y = draw_lines(d, (lx, 384), wrap(d, beat["title"], font(58, "demi"), colw), font(58, "demi"), TEXT, 1.15)
    chip(d, (lx, y + 26), beat["chip"], VIOLET, (34, 28, 66))
    # Right: caption
    rx = W // 2 + phone.w // 2 + phone.bezel + 70
    cf = font(36, "regular")
    lines = wrap(d, beat["caption"], cf, W - rx - 100)
    block_h = int(len(lines) * cf.size * 1.38)
    d.rectangle([rx - 26, H // 2 - block_h // 2 - 6, rx - 21, H // 2 + block_h // 2 - 14], fill=ACCENT)
    draw_lines(d, (rx, H // 2 - block_h // 2), lines, cf, TEXT, 1.38)
    d.text((110, H - 64), footer, font=font(22, "medium"), fill=FAINT)
    return img


def title_card(base: Image.Image, cfg: dict, phone: Phone | None, shot: Image.Image | None) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    x = 150
    d.text((x, 300), "HUAWEI · IMAGINE WHAT'S NEXT · HACKYEAH 2026", font=font(24, "demi"), fill=ACCENT)
    d.text((x, 350), cfg["headline"], font=font(132, "bold"), fill=TEXT)
    y = draw_lines(d, (x, 530), wrap(d, cfg["tagline"], font(46, "medium"), 900), font(46, "medium"), TEXT, 1.25)
    d.text((x, y + 30), cfg["meta"], font=font(30, "regular"), fill=DIM)
    d.text((x, y + 80), cfg["team"], font=font(30, "regular"), fill=DIM)
    d.rounded_rectangle([x, y + 150, x + 6, y + 200], radius=3, fill=VIOLET)
    d.text((x + 24, y + 156), "Human in the loop for AI agents, on HarmonyOS", font=font(28, "medium"), fill=VIOLET)
    if phone is not None and shot is not None:
        phone.paste(img, shot, 1480, H // 2 + 6)
    return img


def end_card(base: Image.Image, cfg: dict) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    cx = W // 2
    d.text((cx, 250), cfg["headline"], font=font(110, "bold"), fill=TEXT, anchor="ma")
    d.text((cx, 410), cfg["repo"], font=font(44, "bold", mono=True), fill=ACCENT, anchor="ma")
    d.text((cx, 490), cfg["team"], font=font(36, "medium"), fill=TEXT, anchor="ma")
    y = draw_lines(d, (cx, 600), wrap(d, "Built with " + cfg["kits"], font(30, "regular"), 1300),
                   font(30, "regular"), DIM, 1.35, anchor_center=True)
    draw_lines(d, (cx, y + 40), wrap(d, cfg["note"], font(26, "regular"), 1300), font(26, "regular"), WARN, 1.35,
               anchor_center=True)
    return img


# ---------------------------------------------------------------------------------------- placeholders
def make_placeholders(build: Path, shots: dict) -> None:
    raw = build / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    frames = []
    t = 0.0
    i = 0
    for beat in shots["beats"]:
        for k in range(6):
            im = Image.new("RGB", (1260, 2720), BG)
            d = ImageDraw.Draw(im)
            d.text((60, 40), "12:00", font=font(40, "demi"), fill=TEXT)
            d.text((60, 160), "Aegis Pocket", font=font(84, "bold"), fill=TEXT)
            d.rounded_rectangle([900, 170, 1200, 240], radius=20, fill=(60, 45, 16))
            d.text((920, 182), "MOCK MODE", font=font(36, "demi"), fill=WARN)
            for r in range(5):
                y = 420 + r * 300 + k * 18
                d.rounded_rectangle([60, y, 1200, y + 250], radius=36, fill=(19, 26, 38), outline=(40, 52, 72), width=3)
            d.text((630, 1950), "PLACEHOLDER", font=font(110, "bold"), fill=(255, 90, 106), anchor="ma")
            d.text((630, 2100), f"{beat['id']} · frame {k + 1}", font=font(70, "demi"), fill=TEXT, anchor="ma")
            name = f"f_{i:05d}.jpeg"
            im.save(raw / name, quality=85)
            frames.append({"file": name, "t": round(t, 2), "beat": beat["id"]})
            t += 0.7
            i += 1
    meta = {"frames": frames, "variants": {}, "skipped": [], "screen": [1260, 2720], "source": "placeholder"}
    (build / "capture.json").write_text(json.dumps(meta, indent=1))


# ---------------------------------------------------------------------------------------- timeline
def caption_for(beat: dict, variant: str | None) -> dict:
    out = {k: beat[k] for k in ("id", "duration", "title", "chip", "caption")}
    if variant and variant != "default":
        out.update(beat.get("variants", {}).get(variant, {}))
    return out


def sample_frames(frames: list[dict], raw: Path, duration: float) -> list[tuple[Path, float]]:
    """Spread the beat's frames over 70% of its time, hold the last (settled) frame for the rest."""
    motion, rest = duration * 0.7, duration * 0.3
    k = max(1, min(len(frames), int(motion * 4)))
    if k == 1:
        picks = [frames[-1]]
    else:
        picks = [frames[round(j * (len(frames) - 1) / (k - 1))] for j in range(k)]
    seq: list[tuple[Path, float]] = []
    last_hash = None
    for fr in picks:
        p = raw / fr["file"]
        h = hashlib.md5(p.read_bytes()).hexdigest()
        dur = motion / len(picks)
        if h == last_hash:
            seq[-1] = (seq[-1][0], seq[-1][1] + dur)
        else:
            seq.append((p, dur))
        last_hash = h
    seq[-1] = (seq[-1][0], seq[-1][1] + rest)
    return seq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--placeholder", action="store_true", help="generate fake frames first (dry run)")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg")
    a = ap.parse_args()

    shots = json.loads((HERE / "shots.json").read_text())
    build, out_dir = Path(a.build), Path(a.out_dir)
    if a.placeholder:
        make_placeholders(build, shots)
    cap = json.loads((build / "capture.json").read_text())
    raw = build / "raw"
    frames_by_beat: dict[str, list[dict]] = {}
    for fr in sorted(cap["frames"], key=lambda f: f["t"]):
        if (raw / fr["file"]).exists():
            frames_by_beat.setdefault(fr["beat"], []).append(fr)

    beats = []
    for b in shots["beats"]:
        if b["id"] in cap.get("skipped", []) or not frames_by_beat.get(b["id"]):
            if b.get("optional") or b["id"] in cap.get("skipped", []):
                print(f"[render] beat {b['id']} skipped (no frames)")
                continue
            print(f"[render] ERROR: no frames for required beat {b['id']}", file=sys.stderr)
            return 1
        beats.append(caption_for(b, cap.get("variants", {}).get(b["id"])))

    total = shots["title"]["duration"] + shots["end"]["duration"] + sum(b["duration"] for b in beats)
    scale = min(1.0, MAX_TOTAL / total)
    if scale < 1.0:
        print(f"[render] planned {total:.1f}s > {MAX_TOTAL}s: scaling durations by {scale:.3f}")

    frames_dir = build / "composed"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = background()
    first_shot = Image.open(raw / frames_by_beat[beats[0]["id"]][-1]["file"])
    phone = Phone(first_shot)
    footer = shots["footer"] + ("  ·  PLACEHOLDER FRAMES (dry run)" if cap.get("source") == "placeholder" else "")

    # Stills are written to disk as soon as they are composed (keeps memory low on an 8 GB machine).
    counter = [0]

    def save(img: Image.Image) -> Path:
        p = frames_dir / f"c_{counter[0]:04d}.png"
        counter[0] += 1
        img.save(p, compress_level=1)
        return p

    segments: list[list[tuple[Path, float]]] = []
    title = title_card(base, shots["title"], phone, first_shot)
    segments.append([(save(title), shots["title"]["duration"] * scale)])
    timeline = [("title", shots["title"]["duration"] * scale, shots["title"]["headline"], shots["title"]["tagline"])]
    for n, b in enumerate(beats, start=1):
        seg = []
        for p, dur in sample_frames(frames_by_beat[b["id"]], raw, b["duration"] * scale):
            with Image.open(p) as shot:
                seg.append((save(compose_beat(base, phone, shot.convert("RGB"), b, n, len(beats), footer)), dur))
        segments.append(seg)
        timeline.append((b["id"], b["duration"] * scale, b["title"], b["caption"]))
    segments.append([(save(end_card(base, shots["end"])), shots["end"]["duration"] * scale)])
    timeline.append(("end", shots["end"]["duration"] * scale, shots["end"]["repo"], shots["end"]["note"]))

    def blend(pa, pb, alpha: float) -> Path:
        ia = pa if isinstance(pa, Image.Image) else Image.open(pa).convert("RGB")
        ib = pb if isinstance(pb, Image.Image) else Image.open(pb).convert("RGB")
        return save(Image.blend(ia, ib, alpha))

    # Flatten with crossfades (the blend time comes out of the outgoing segment's last hold).
    entries: list[tuple[Path, float]] = []
    black = Image.new("RGB", (W, H), (0, 0, 0))
    step = 1.0 / FPS
    for j in range(1, 7):  # fade in
        entries.append((blend(black, segments[0][0][0], j / 7), step))
    for si, seg in enumerate(segments):
        seg = list(seg)
        if si == 0:
            seg[0] = (seg[0][0], seg[0][1] - 6 * step)
        if si < len(segments) - 1:
            pth, dur = seg[-1]
            seg[-1] = (pth, max(step, dur - XFADE))
        entries.extend(seg)
        if si < len(segments) - 1:
            pa, pb = seg[-1][0], segments[si + 1][0][0]
            for j in range(1, XFADE_STEPS + 1):
                entries.append((blend(pa, pb, j / (XFADE_STEPS + 1)), XFADE / XFADE_STEPS))
    last, dur = entries[-1]
    entries[-1] = (last, max(step, dur - 8 * step))
    for j in range(1, 9):  # fade out
        entries.append((blend(last, black, j / 8), step))

    concat = [f"file '{pth}'\nduration {dur:.4f}" for pth, dur in entries]
    concat.append(f"file '{entries[-1][0]}'")
    (build / "concat.txt").write_text("\n".join(concat) + "\n")
    total_s = sum(d for _, d in entries)
    print(f"[render] {len(entries)} timed stills ({counter[0]} PNGs), {total_s:.2f}s")

    mp4 = out_dir / "aegis-pocket-demo-60s.mp4"
    cmd = [a.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(build / "concat.txt"),
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-vf", f"fps={FPS},scale={W}:{H},format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "64k", "-t", f"{min(total_s, 58.0):.3f}", "-shortest",
           "-movflags", "+faststart", str(mp4)]
    subprocess.run(cmd, check=True)
    title.save(out_dir / "cover.png")

    # captions timeline (cumulative, approximate: crossfades overlap by XFADE)
    t = 0.0
    lines_txt, srt = [], []
    for k, (bid, dur, head, cap_text) in enumerate(timeline, start=1):
        start, end = t, t + dur
        lines_txt.append(f"{start:5.1f}-{end:5.1f}s  [{bid}] {head}: {cap_text}")
        srt.append(f"{k}\n{_ts(start)} --> {_ts(end)}\n{head}: {cap_text}\n")
        t = end
    (out_dir / "captions.txt").write_text("\n".join(lines_txt) + "\n")
    (out_dir / "captions.srt").write_text("\n".join(srt))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height",
                            "-of", "default=nw=1", str(mp4)], capture_output=True, text=True).stdout
    print("[render] wrote", mp4, "\n" + probe.strip())
    return 0


def _ts(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


if __name__ == "__main__":
    sys.exit(main())
