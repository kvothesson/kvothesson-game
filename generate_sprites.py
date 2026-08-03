# -*- coding: utf-8 -*-
"""
KVOTHESSON GAME POC - generador de frames del sprite sheet.

Protocolo de anclaje (mismo que el_uncido): UNA sola imagen se genera desde
texto (K-BASE, el idle neutro de perfil). Los 22 frames restantes se generan
SIEMPRE por referencia adjuntando K-BASE, nunca desde texto. Eso es lo que
evita que el poncho, la barba o el largo del pelo cambien entre frames y que
la caminata "vibre".

Uso:
  python generate_sprites.py --ancla          # solo K-BASE
  python generate_sprites.py                  # todo lo que falte (resume)
  python generate_sprites.py walk_03 walk_04  # ids puntuales
  python generate_sprites.py --force walk_03  # regenera aunque exista
  python generate_sprites.py --list           # lista los ids y su estado
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
RAW = BASE / "raw"
RAW.mkdir(parents=True, exist_ok=True)

MODEL = "gemini-3-pro-image"


def api_key() -> str:
    for p in [BASE / ".env", BASE.parent.parent / ".env"]:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith(("GEMINI_API_KEY=", "GOOGLE_API_KEY=")) and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    sys.exit("[X] No encontre GEMINI_API_KEY ni GOOGLE_API_KEY en .env")


URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key()}"

STYLE = ("in high-end cyberpunk anime style, cel-shaded, sharp line art, "
         "vibrant colors, Studio aesthetic, flat color, game sprite artwork")

# El modelo de personaje va BLOQUEADO. El canon deja el poncho sin especificar
# a proposito, pero un sprite sheet necesita un modelo fijo o el personaje
# parpadea entre frames. Excepcion deliberada, documentada en el README.
KVOTHESSON = (
    "Kvothesson, the Architect of Silicon: an Argentine man in his 30s, athletic "
    "build, long black hair pulled into a high ponytail with tightly shaved sides, "
    "thick black beard with sharp precise edges, calm intense gaze. He wears a "
    "heavy woven poncho in deep indigo blue with a single horizontal band of pale "
    "bone white near the hem, over dark charcoal simple clothing, dark leather "
    "boots and dark forearm wraps. A small luminous hexagonal crystal glows warm "
    "amber at the center of his chest, over the poncho. No armor, no plating, no "
    "runes, no weapon, no cape, no hood, no hat."
)

# Encuadre. Va IDENTICO en las 23 llamadas. Es lo que permite despues alinear
# los frames por pivote sin que el personaje salte de tamano.
SHOT = (
    "CRITICAL CAMERA RULE, this is a strict left-facing-right PROFILE VIEW at "
    "exactly 90 degrees, like a side-scroller video game sprite. The camera is "
    "directly at his LEFT side. You see ONE eye only, ONE ear only, ONE arm "
    "clearly and the far arm mostly hidden behind the body, ONE leg clearly and "
    "the far leg mostly hidden behind the near leg. The nose, the lips, the beard "
    "and the chin all read as a clean silhouette against the background. The chest "
    "and the shoulders are turned fully sideways: you do NOT see the front of the "
    "chest, you do NOT see both shoulders, you do NOT see both sides of the "
    "poncho. This is NOT a three quarter view and NOT a front view. "
    "FULL BODY: the entire figure from the top of the hair to the soles of the "
    "boots is inside the frame. Camera at chest height, dead straight on, flat "
    "orthographic framing, no perspective distortion, no foreshortening. The "
    "figure is horizontally centered and fills only about 60 percent of the frame "
    "height, leaving generous empty background above the head, below the feet and "
    "on both sides."
)

# Fondo croma. Sin piso, sin sombra, sin luz de fondo: cualquiera de las tres
# cosas arruina el recorte por chroma key.
CHROMA = (
    "Background is ONE solid uniform pure green #00FF00 chroma key screen, "
    "absolutely flat, no gradient, no texture, no vignette, no floor, no ground "
    "line, no horizon, no scenery, no props. NO shadow anywhere, no contact "
    "shadow under the feet, no drop shadow, no green rim light and no green "
    "reflection on the character. Nothing green anywhere on the character himself."
)

LIGHT = (
    "Neutral game-ready lighting: a cold blue-white key light from the upper left, "
    "soft fill so no area is crushed to pure black, and a warm amber bounce on the "
    "jaw and forearms coming from the chest crystal."
)

CLEAN = (
    "Clean illustration. ABSOLUTELY NO TEXT anywhere: no letters, no words, no "
    "numbers, no glyphs, no captions, no labels, no watermarks, no signature, no "
    "grid, no reference lines. Exactly ONE character in frame. Full bleed edge to "
    "edge: no black bars, no letterboxing, no border, no frame, no panel."
)

# Cadena que va en TODOS los derivados. "Cambia solo la pose" es la instruccion
# que sostiene la identidad frame a frame.
KEEP = (
    "Use the attached image as the absolute reference for the character. Keep his "
    "design, face, beard, hairstyle, poncho color and pattern, clothing, boots, "
    "proportions, body height, materials, palette and line weight EXACTLY as shown. "
    "SAME SHOT as the reference: identical camera distance, identical camera angle, "
    "identical framing, identical scale of the figure in frame, identical lighting, "
    "identical background, identical color grade. He is still seen in STRICT 90 "
    "degree side profile facing screen RIGHT, exactly as in the reference: one eye, "
    "one ear, the far arm and far leg mostly hidden behind the near ones, the chest "
    "turned fully sideways. NOT three quarter, NOT front view. The figure keeps the "
    "same height in frame as the reference, about 60 percent, with the same empty "
    "margins. His feet rest on the same invisible ground line at the same height in "
    "frame. Change ONLY the body pose described next, nothing else. "
)

# ---------------------------------------------------------------------------
# id, pose. Todos cuelgan de K-BASE salvo K-BASE mismo.
# Ciclo de caminata estandar de 8 frames: contact / down / pass / up, x2.
# ---------------------------------------------------------------------------
FRAMES = [
    # ---------- ANCLA ----------
    ("K-BASE", None,
     "standing at rest in a relaxed neutral idle: weight evenly on both feet, feet "
     "flat on the ground and slightly apart, spine straight, shoulders level and "
     "relaxed, both arms hanging loose and open at his sides, head level looking "
     "forward to the right. The poncho hangs straight down, still. The chest "
     "crystal glows dim and steady."),

    # ---------- IDLE (4) ----------
    ("idle_00", "K-BASE",
     "the exact neutral idle of the reference: weight even on both feet, arms loose "
     "at his sides, poncho hanging straight and still, chest crystal dim."),
    ("idle_01", "K-BASE",
     "mid inhale: the chest is slightly expanded, both shoulders lifted a very small "
     "amount, the head raised a hair. The hem of the poncho drifts back a little in "
     "a soft breeze. The chest crystal glows a little brighter. Feet do not move."),
    ("idle_02", "K-BASE",
     "full exhale: the shoulders have settled to their lowest point, the chest is "
     "relaxed, the head tilted down a very small amount. The poncho hem has fallen "
     "back down and hangs still. The chest crystal is at its dimmest. Feet do not "
     "move."),
    ("idle_03", "K-BASE",
     "starting to inhale again: shoulders rising slightly from their lowest point, "
     "head coming back to level, the poncho hem just beginning to lift and drift "
     "back. The chest crystal is brightening. Feet do not move."),

    # ---------- WALK (8) ----------
    ("walk_00", "K-BASE",
     "WALK CYCLE frame 1 of 8, CONTACT pose: the right leg is stretched forward with "
     "the right heel striking the ground, the left leg is stretched back behind him "
     "with only the left toe touching the ground. Both legs are nearly straight, "
     "forming a wide open stride like an upside down V. The torso is upright over the "
     "middle. The LEFT arm swings forward and the RIGHT arm swings back, opposite to "
     "the legs. The poncho hem trails backward."),
    ("walk_01", "K-BASE",
     "WALK CYCLE frame 2 of 8, DOWN pose: the body is at its LOWEST point, the whole "
     "figure has dropped down. All the weight is on the right leg which is now flat "
     "on the ground with the knee clearly bent to absorb it. The left leg has lifted "
     "off behind and its knee is bending as it starts to come forward. Arms are "
     "swinging toward neutral, left arm still slightly forward. The poncho hem drops "
     "and settles low."),
    ("walk_02", "K-BASE",
     "WALK CYCLE frame 3 of 8, PASSING pose: the body is at its HIGHEST point, "
     "pushed up on the straight right leg which is vertical under the body. The left "
     "leg passes directly beside it, knee lifted and bent, left foot just clearing "
     "the ground. Both arms hang almost straight down at his sides, crossing at "
     "neutral. Torso upright and tall. The poncho hangs almost straight."),
    ("walk_03", "K-BASE",
     "WALK CYCLE frame 4 of 8, UP pose: the body is rising and moving forward, "
     "carried on the right leg which is now behind vertical with the right heel "
     "starting to lift. The left leg is reaching forward, knee straightening, left "
     "foot ahead of the body about to land. The RIGHT arm is swinging forward and "
     "the LEFT arm swinging back. The poncho hem lifts backward."),
    ("walk_04", "K-BASE",
     "WALK CYCLE frame 5 of 8, CONTACT pose mirrored from frame 1: now the LEFT leg "
     "is stretched forward with the left heel striking the ground, and the RIGHT leg "
     "is stretched back behind him with only the right toe touching. Wide open "
     "stride, both legs nearly straight. Torso upright. The RIGHT arm swings forward "
     "and the LEFT arm swings back. The poncho hem trails backward. He still faces "
     "screen right, this is NOT a flipped image."),
    ("walk_05", "K-BASE",
     "WALK CYCLE frame 6 of 8, DOWN pose mirrored: the body is at its LOWEST point. "
     "All the weight is on the LEFT leg, flat on the ground with the knee clearly "
     "bent. The right leg has lifted off behind and its knee is bending as it starts "
     "forward. Arms swinging toward neutral, right arm still slightly forward. The "
     "poncho hem drops and settles low."),
    ("walk_06", "K-BASE",
     "WALK CYCLE frame 7 of 8, PASSING pose mirrored: the body is at its HIGHEST "
     "point, pushed up on the straight LEFT leg, vertical under the body. The right "
     "leg passes beside it, knee lifted and bent, right foot just clearing the "
     "ground. Both arms hang almost straight down at neutral. Torso upright and "
     "tall. The poncho hangs almost straight."),
    ("walk_07", "K-BASE",
     "WALK CYCLE frame 8 of 8, UP pose mirrored: the body is rising and moving "
     "forward on the LEFT leg, now behind vertical with the left heel lifting. The "
     "right leg reaches forward, knee straightening, right foot ahead of the body "
     "about to land. The LEFT arm swings forward and the RIGHT arm swings back. The "
     "poncho hem lifts backward."),

    # ---------- RUN (6) ----------
    ("run_00", "K-BASE",
     "RUN CYCLE frame 1 of 6, CONTACT: sprinting hard. The torso leans clearly "
     "forward from the hips. The right foot lands under the body with the knee bent, "
     "taking the impact. The left leg is folded up behind with the left heel kicked "
     "close to the buttock. Both arms are bent about 90 degrees at the elbow and "
     "pumping: LEFT elbow driven forward and up, RIGHT elbow driven back. The poncho "
     "streams backward almost horizontally behind him."),
    ("run_01", "K-BASE",
     "RUN CYCLE frame 2 of 6, PUSH OFF: the right leg extends powerfully behind him, "
     "fully straight, pushing off the toe, launching the body up and forward. The "
     "left knee drives high and forward in front, thigh close to horizontal. Torso "
     "leaning forward. Arms bent 90 degrees still pumping opposite. The poncho "
     "streams backward almost horizontally."),
    ("run_02", "K-BASE",
     "RUN CYCLE frame 3 of 6, AIRBORNE: both feet are completely off the ground, the "
     "whole figure floating at the top of the run. The left leg is extended forward "
     "reaching for the next step, the right leg folded up behind. The torso leans "
     "forward. Arms bent 90 degrees, LEFT arm forward. The poncho flares out fully "
     "behind him, horizontal and rippling."),
    ("run_03", "K-BASE",
     "RUN CYCLE frame 4 of 6, CONTACT mirrored: the LEFT foot lands under the body "
     "with the knee bent taking the impact, and the right leg is folded up behind "
     "with the heel kicked close to the buttock. Torso leaning forward. Arms bent "
     "90 degrees: RIGHT elbow driven forward and up, LEFT elbow driven back. The "
     "poncho streams backward. He still faces screen right, this is NOT a flipped "
     "image."),
    ("run_04", "K-BASE",
     "RUN CYCLE frame 5 of 6, PUSH OFF mirrored: the LEFT leg extends fully straight "
     "behind him pushing off the toe, while the right knee drives high and forward in "
     "front with the thigh close to horizontal. Torso leaning forward. Arms bent 90 "
     "degrees pumping opposite. The poncho streams backward almost horizontally."),
    ("run_05", "K-BASE",
     "RUN CYCLE frame 6 of 6, AIRBORNE mirrored: both feet completely off the ground, "
     "the figure floating. The right leg extended forward reaching for the next step, "
     "the left leg folded up behind. Torso leaning forward. Arms bent 90 degrees, "
     "RIGHT arm forward. The poncho flares out fully behind him, horizontal and "
     "rippling."),

    # ---------- JUMP (3) ----------
    ("jump_00", "K-BASE",
     "JUMP, launch: he has just exploded upward off the ground. Both legs are "
     "extended straight down and back, toes pointed, the body stretched tall and "
     "vertical. Both arms are thrown upward past his head. The chest crystal flares "
     "bright. The poncho is pulled sharply downward and outward by the acceleration, "
     "flaring wide below him."),
    ("jump_01", "K-BASE",
     "JUMP, apex: floating at the top of the jump, weightless. The knees are tucked "
     "up toward the chest, the body compact and slightly curled forward. The arms are "
     "out to the sides for balance, elbows soft. The poncho floats up and outward "
     "around him, spread and weightless."),
    ("jump_02", "K-BASE",
     "JUMP, falling: descending fast. Both legs reach downward and forward, knees "
     "slightly bent, feet leading, ready to absorb the landing. The torso leans back "
     "a little, both arms out and slightly back for balance. The poncho is dragged "
     "upward by the fall, flaring up above and behind his shoulders."),

    # ---------- LAND (1) ----------
    ("land_00", "K-BASE",
     "LANDING impact: a deep crouch absorbing the hit. Both feet flat on the ground "
     "and apart, both knees deeply bent, hips low, the torso folded forward over the "
     "knees, the head down. One hand reaches down and touches the ground beside his "
     "front foot. The poncho collapses down around him and pools. The chest crystal "
     "flares bright from the impact."),
]

SPEC = {fid: (parent, pose) for fid, parent, pose in FRAMES}
ORDER = [fid for fid, _, _ in FRAMES]


def img_part(path: Path) -> dict:
    return {"inline_data": {"mime_type": "image/png",
                            "data": base64.b64encode(path.read_bytes()).decode()}}


# Pacing fijo entre llamadas. Comerse el backoff por 429 sale mas caro en
# tiempo que esperar un poco entre pedidos.
PACE = 8.0
_last = [0.0]


def call_api(parent, prompt: str, dest: Path, size: str) -> bool:
    espera = PACE - (time.monotonic() - _last[0])
    if espera > 0:
        time.sleep(espera)
    _last[0] = time.monotonic()

    parts = []
    if parent:
        parts.append(img_part(RAW / f"{parent}.png"))
    parts.append({"text": prompt})

    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": "3:4",
                                                 "imageSize": size}}}
    for attempt in range(3):
        try:
            r = requests.post(URL, json=body, timeout=300)
            if r.status_code == 200:
                for part in r.json()["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        dest.write_bytes(base64.b64decode(part["inlineData"]["data"]))
                        return True
                print(f"    SIN IMAGEN: {json.dumps(r.json())[:300]}")
                return False
            print(f"    HTTP {r.status_code} (intento {attempt+1}): {r.text[:250]}")
            if r.status_code in (429, 500, 503):
                time.sleep(20 * (attempt + 1))
                continue
            return False
        except requests.RequestException as e:
            print(f"    ERROR (intento {attempt+1}): {e}")
            time.sleep(10)
    return False


def build_prompt(fid: str, parent, pose: str) -> str:
    if parent is None:
        # Unica generacion desde texto de todo el proyecto.
        return (f"{KVOTHESSON} He is {pose} {SHOT} {LIGHT} {CHROMA} {CLEAN} {STYLE}")
    return (f"{KEEP}NEW POSE: he is {pose} {CHROMA} {CLEAN} {STYLE}")


def generate(fid: str, force: bool = False) -> bool:
    parent, pose = SPEC[fid]
    dest = RAW / f"{fid}.png"
    if dest.exists() and not force:
        print(f"[=] {fid} ya existe")
        return True
    if parent and not (RAW / f"{parent}.png").exists():
        print(f"[X] {fid}: falta el ancla {parent}. Corre --ancla primero.")
        return False

    size = "2K" if parent is None else "1K"
    print(f"[>] {fid} ({'texto' if parent is None else 'ref ' + parent}, {size})")
    ok = call_api(parent, build_prompt(fid, parent, pose), dest, size)
    print(f"    {'OK' if ok else 'FALLO'} -> {dest.name}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="ids puntuales a generar")
    ap.add_argument("--ancla", action="store_true", help="solo K-BASE")
    ap.add_argument("--force", action="store_true", help="regenera aunque exista")
    ap.add_argument("--list", action="store_true", help="lista ids y estado")
    args = ap.parse_args()

    if args.list:
        for fid in ORDER:
            estado = "OK " if (RAW / f"{fid}.png").exists() else "-- "
            print(f"{estado} {fid}")
        return

    if args.ancla:
        objetivo = ["K-BASE"]
    elif args.ids:
        desconocidos = [i for i in args.ids if i not in SPEC]
        if desconocidos:
            sys.exit(f"[X] ids desconocidos: {desconocidos}")
        objetivo = args.ids
    else:
        objetivo = ORDER

    fallos = []
    for fid in objetivo:
        if not generate(fid, force=args.force):
            fallos.append(fid)

    print(f"\n=== {len(objetivo) - len(fallos)}/{len(objetivo)} generados ===")
    if fallos:
        print("fallaron: " + " ".join(fallos))
        print("reintenta con: python generate_sprites.py " + " ".join(fallos))


if __name__ == "__main__":
    main()
