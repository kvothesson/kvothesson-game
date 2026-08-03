# -*- coding: utf-8 -*-
"""
KVOTHESSON GAME POC - compositor del sprite sheet.

Toma los PNG crudos de raw/ (personaje sobre croma verde) y produce:
  docs/kvothesson.png   sheet en grilla, una fila por animacion
  docs/atlas.json       geometria, pivote, fps y zancada de cada animacion
  qa/contacto.png      contact sheet con indices, para revisar frame a frame
  qa/onion_<anim>.png  onion skin de un ciclo, para ver la deriva

Lo que hace que la animacion no tiemble, en orden de importancia:

1. CHROMA KEY POR COMPONENTE CONECTADA. Se borra solo el verde que toca el
   borde del cuadro, no todo pixel verdoso. Asi un reflejo verde dentro del
   personaje no le abre un agujero.
2. NORMALIZACION DE ESCALA POR GRUPO. El modelo dibuja al personaje un poco
   mas grande o mas chico en cada frame. Se lleva cada frame a la altura
   mediana de su ciclo, con una banda muerta del 4% para no aplastar el
   rebote vertical real de la caminata.
3. ALINEADO POR PIVOTE. En frames con los pies en el piso el pivote es
   (centroide horizontal de los pies, base del bounding box). En frames en el
   aire es (centroide horizontal del cuerpo, base + correccion de pies
   recogidos). El pivote queda HORNEADO en la celda: el motor dibuja siempre
   la celda entera en la misma posicion y no necesita offsets por frame.
4. MEDICION DE ZANCADA. Se mide la apertura de piernas en el frame de
   contacto y se guarda en el atlas. El motor deriva los fps de la caminata
   de la velocidad real, y por eso el pie no patina sobre el piso.

Uso:
  python build_sheet.py            # construye todo
  python build_sheet.py --report   # solo mide y reporta, no escribe nada
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

BASE = Path(__file__).parent
RAW = BASE / "raw"
WEB = BASE / "docs"   # GitHub Pages solo sirve desde la raiz o desde docs/
QA = BASE / "qa"

# --- chroma key ---------------------------------------------------------
# "verdor" = G - max(R,B). El fondo #00FF00 da 255. La piel y el poncho dan
# negativo. La rampa entre LO y HI es el antialias del borde.
KEY_LO, KEY_HI = 40.0, 110.0

# Altura del personaje parado, en pixeles, dentro de la celda final.
STAND_H = 200
# Margen de la celda, en pixeles.
PAD = 6

# Modo de anclaje horizontal. Elegir mal esto es lo que hace que un ciclo se
# hamaque de lado a lado.
#   "pies"   centroide de la banda de pies. Sirve cuando en cada frame los
#            apoyos quedan repartidos alrededor del cuerpo: idle, caminata.
#   "cabeza" centroide del 14% superior. Sirve en la carrera, donde en cada
#            frame apoya un solo pie que alterna adelante y atras y arrastraria
#            el centroide de un lado al otro.
#   "cuerpo" centroide de toda la silueta. Para frames en el aire.
ANIMS = [
    # nombre, frames, fps base, loopea, ancla horizontal, normaliza escala
    ("idle",  [f"idle_{i:02d}" for i in range(4)], 4,  True,  "pies",   True),
    ("walk",  [f"walk_{i:02d}" for i in range(8)], 12, True,  "pies",   True),
    ("run",   [f"run_{i:02d}" for i in range(6)],  16, True,  "cabeza", True),
    ("jump",  ["jump_00", "jump_01", "jump_02"],   10, False, "cuerpo", False),
    ("land",  ["land_00"],                          1, False, "pies",   False),
]

# Cuanto sube los pies el frame respecto de su linea de piso real, como
# fraccion de la altura del personaje parado. Solo importa en el aire: si no
# se corrige, al recoger las piernas el personaje parece caerse de golpe.
GROUND_LIFT = {"jump_00": 0.00, "jump_01": 0.30, "jump_02": 0.02}

# Como se calcula cuanto mundo cubre un ciclo completo.
#
#   ("medida", k)  k por el paso medido en el contact pose. El paso NO es el
#                  ancho de la banda de pies: ese ancho va de la punta del pie
#                  de atras a la punta del de adelante, o sea el paso MAS un
#                  largo de bota. Si no se resta la bota, la zancada sale ~35%
#                  larga, y como el motor deriva la velocidad de la zancada,
#                  el personaje termina caminando demasiado rapido.
#   ("altura", k)  k por la altura del personaje. Se usa en la carrera, donde
#                  el frame aereo no apoya y la medida no significa nada.
#                  1.45 de la altura es una zancada de carrera normal.
ZANCADA = {
    "idle": ("altura", 0.0),
    "walk": ("medida", 2.0),
    "run":  ("altura", 1.45),
    "jump": ("altura", 0.0),
    "land": ("altura", 0.0),
}


# ---------------------------------------------------------------------------
# 1. keying
# ---------------------------------------------------------------------------
def key_green(path: Path) -> np.ndarray:
    """Devuelve RGBA float32 con el croma borrado y el derrame verde corregido."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"[X] no pude leer {path}")
    b, g, r = (img[:, :, i].astype(np.float32) for i in range(3))

    verdor = g - np.maximum(r, b)
    # alpha continuo: 1 adentro, 0 en el croma puro, rampa en el borde
    alpha = np.clip((KEY_HI - verdor) / (KEY_HI - KEY_LO), 0.0, 1.0)

    # Se borra el croma conectado al borde del cuadro, mas cualquier bolsa de
    # croma ENCERRADA que sea verde casi puro: el modelo suele dejar una entre
    # las piernas o bajo un brazo, y esa bolsa no toca el borde. Un verde
    # apenas verdoso encerrado (un reflejo sobre el personaje) se conserva.
    fondo = alpha < 0.5
    etiquetas, n = ndimage.label(fondo)
    if n:
        ids = np.arange(1, n + 1)
        borde = set(etiquetas[0, :]) | set(etiquetas[-1, :]) | \
                set(etiquetas[:, 0]) | set(etiquetas[:, -1])
        borde.discard(0)
        medias = ndimage.mean(verdor, etiquetas, ids)
        tam = ndimage.sum(np.ones_like(verdor), etiquetas, ids)
        croma = {int(i) for i, m, s in zip(ids, medias, tam)
                 if m > 150.0 and s >= 40}
        quitar = borde | croma
        conservar = fondo & ~np.isin(etiquetas, list(quitar))
        alpha = np.where(conservar, 1.0, alpha)

    # Despill: el verde que quedo pegado en el contorno se baja al nivel de
    # los otros dos canales. Sin esto queda un halo acido alrededor.
    limite = (r + b) * 0.5 + 12.0
    g = np.minimum(g, np.maximum(limite, g * 0.35 + limite * 0.65))

    return np.dstack([r, g, b, alpha * 255.0]).astype(np.float32)


# ---------------------------------------------------------------------------
# 2. geometria
# ---------------------------------------------------------------------------
def bbox(alpha: np.ndarray, umbral: float = 24.0):
    filas = np.where(alpha.max(axis=1) > umbral)[0]
    cols = np.where(alpha.max(axis=0) > umbral)[0]
    if not len(filas) or not len(cols):
        raise SystemExit("[X] frame vacio despues del keying")
    return cols[0], filas[0], cols[-1] + 1, filas[-1] + 1  # x0,y0,x1,y1


def pivote_x(alpha: np.ndarray, y0: int, y1: int, modo: str) -> float:
    """Centroide horizontal de la banda de referencia segun el modo de anclaje."""
    alto = y1 - y0
    if modo == "pies":
        banda = alpha[max(y0, y1 - max(4, int(alto * 0.06))):y1, :]
    elif modo == "cabeza":
        banda = alpha[y0:y0 + max(6, int(alto * 0.14)), :]
    else:
        banda = alpha[y0:y1, :]
    peso = banda.sum(axis=0)
    total = peso.sum()
    if total <= 0:
        return alpha.shape[1] / 2.0
    return float((np.arange(alpha.shape[1]) * peso).sum() / total)


def apertura_pies(alpha: np.ndarray, y0: int, y1: int) -> float:
    """Ancho de la banda de pies. En el contact pose es la zancada."""
    alto = y1 - y0
    banda = alpha[max(y0, y1 - max(4, int(alto * 0.06))):y1, :]
    cols = np.where(banda.max(axis=0) > 24.0)[0]
    return float(cols[-1] - cols[0]) if len(cols) else 0.0


# ---------------------------------------------------------------------------
# 3. pipeline
# ---------------------------------------------------------------------------
def medir():
    datos = {}
    for anim, ids, _, _, modo, _ in ANIMS:
        for fid in ids:
            p = RAW / f"{fid}.png"
            if not p.exists():
                raise SystemExit(f"[X] falta {p.name}. Corre generate_sprites.py")
            rgba = key_green(p)
            a = rgba[:, :, 3]
            x0, y0, x1, y1 = bbox(a)
            datos[fid] = {
                "anim": anim, "rgba": rgba, "box": (x0, y0, x1, y1),
                "h": y1 - y0, "w": x1 - x0,
                "px": pivote_x(a, y0, y1, modo),
                "pies": apertura_pies(a, y0, y1),
            }
    return datos


def normalizar_escala(datos):
    """Lleva cada frame a la altura mediana de su ciclo. Banda muerta del 4%."""
    for anim, ids, _, _, _, normaliza in ANIMS:
        alturas = [datos[f]["h"] for f in ids]
        med = float(np.median(alturas))
        for fid in ids:
            s = med / datos[fid]["h"]
            if not normaliza or abs(s - 1.0) < 0.04:
                s = 1.0
            datos[fid]["s_local"] = float(np.clip(s, 0.82, 1.22))
            datos[fid]["h_norm"] = datos[fid]["h"] * datos[fid]["s_local"]
        datos.setdefault("_med", {})[anim] = med
    return datos


def construir(report_only: bool = False):
    datos = medir()
    normalizar_escala(datos)

    # Escala global: el idle parado mide STAND_H en la celda final.
    base_h = datos["idle_00"]["h_norm"]
    g = STAND_H / base_h

    print(f"{'frame':10} {'bbox':>12} {'s_local':>8} {'final':>7} {'pies':>6}")
    for anim, ids, _, _, _, _ in ANIMS:
        for fid in ids:
            d = datos[fid]
            print(f"{fid:10} {d['w']:5}x{d['h']:<6} {d['s_local']:8.3f} "
                  f"{d['h_norm']*g:7.1f} {d['pies']*d['s_local']*g:6.1f}")

    # Extension maxima respecto del pivote, para dimensionar la celda.
    izq = der = arr = aba = 0.0
    for anim, ids, _, _, _, _ in ANIMS:
        for fid in ids:
            d = datos[fid]
            x0, y0, x1, y1 = d["box"]
            s = d["s_local"] * g
            lift = GROUND_LIFT.get(fid, 0.0) * STAND_H
            izq = max(izq, (d["px"] - x0) * s)
            der = max(der, (x1 - d["px"]) * s)
            arr = max(arr, (y1 - y0) * s + lift)
            aba = max(aba, lift * 0 + 0.0)

    cw = int(math.ceil(izq + der)) + PAD * 2
    ch = int(math.ceil(arr + aba)) + PAD * 2
    pvx = PAD + izq
    pvy = PAD + arr
    cols = max(len(ids) for _, ids, _, _, _, _ in ANIMS)

    print(f"\ncelda {cw}x{ch}  pivote ({pvx:.1f},{pvy:.1f})  "
          f"grilla {cols}x{len(ANIMS)}  personaje {STAND_H}px")

    if report_only:
        return

    WEB.mkdir(exist_ok=True)
    QA.mkdir(exist_ok=True)
    sheet = Image.new("RGBA", (cw * cols, ch * len(ANIMS)), (0, 0, 0, 0))
    recortes = {}

    for fila, (anim, ids, fps, loop, _modo, _) in enumerate(ANIMS):
        for col, fid in enumerate(ids):
            d = datos[fid]
            x0, y0, x1, y1 = d["box"]
            s = d["s_local"] * g
            crop = d["rgba"][y0:y1, x0:x1]
            nw = max(1, int(round((x1 - x0) * s)))
            nh = max(1, int(round((y1 - y0) * s)))
            # INTER_AREA es el unico que no ensucia el line art al bajar.
            chico = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
            im = Image.fromarray(np.clip(chico, 0, 255).astype(np.uint8), "RGBA")

            lift = GROUND_LIFT.get(fid, 0.0) * STAND_H
            dx = int(round(pvx - (d["px"] - x0) * s))
            dy = int(round(pvy - nh - lift))
            sheet.alpha_composite(im, (col * cw + dx, fila * ch + dy))
            recortes[fid] = (im, dx, dy)

    sheet.save(WEB / "kvothesson.png")

    atlas = {
        "image": "kvothesson.png",
        "cell": {"w": cw, "h": ch},
        "pivot": {"x": round(pvx, 1), "y": round(pvy, 1)},
        "standHeight": STAND_H,
        "anims": {},
    }
    # Con los pies juntos y de perfil, la banda de pies del idle mide exactamente
    # un largo de bota. Es lo que hay que descontarle al paso medido.
    bota = datos["idle_00"]["pies"] * datos["idle_00"]["s_local"] * g
    print(f"\nlargo de bota (del idle): {bota:.1f}px")

    for fila, (anim, ids, fps, loop, _modo, _) in enumerate(ANIMS):
        modo, k = ZANCADA.get(anim, ("altura", 0.0))
        if modo == "medida":
            span = max(datos[f]["pies"] * datos[f]["s_local"] * g for f in ids)
            ciclo = max(0.0, span - bota) * k
        else:
            ciclo = STAND_H * k
        atlas["anims"][anim] = {
            "row": fila,
            "frames": len(ids),
            "fps": fps,
            "loop": loop,
            # distancia de mundo que cubre un ciclo completo, en px del sprite
            "cycleDistance": round(ciclo, 1) or 1.0,
        }
    (WEB / "atlas.json").write_text(json.dumps(atlas, indent=2), encoding="utf-8")
    # Copia como .js para que la PoC tambien abra con doble click (file://),
    # donde fetch() de un json local esta bloqueado por CORS.
    (WEB / "atlas.js").write_text("window.ATLAS = " + json.dumps(atlas, indent=2) + ";\n",
                                  encoding="utf-8")

    qa_contacto(recortes, cw, ch, pvx, pvy)
    for anim in ("walk", "run", "idle", "jump"):
        qa_onion(recortes, anim, cw, ch, pvx, pvy)

    print(f"\nOK -> {WEB/'kvothesson.png'} ({sheet.width}x{sheet.height})")
    print(f"OK -> {WEB/'atlas.json'}")
    print(f"OK -> {QA/'contacto.png'} y onion skins")


# ---------------------------------------------------------------------------
# 4. QA visual
# ---------------------------------------------------------------------------
def damero(w: int, h: int, paso: int = 16) -> Image.Image:
    im = Image.new("RGB", (w, h), (58, 58, 66))
    d = ImageDraw.Draw(im)
    for y in range(0, h, paso):
        for x in range(0, w, paso):
            if (x // paso + y // paso) % 2 == 0:
                d.rectangle([x, y, x + paso - 1, y + paso - 1], fill=(74, 74, 84))
    return im


def qa_contacto(recortes, cw: int, ch: int, pvx: float, pvy: float) -> None:
    """Contact sheet con el pivote real dibujado. Los sprites van colocados
    exactamente donde quedaron en el sheet, asi que esto tambien valida el
    alineado y no solo el recorte."""
    cols = max(len(ids) for _, ids, _, _, _, _ in ANIMS)
    im = damero(cw * cols, ch * len(ANIMS))
    d = ImageDraw.Draw(im)
    for fila, (anim, ids, _, _, _, _) in enumerate(ANIMS):
        for col, fid in enumerate(ids):
            ox, oy = col * cw, fila * ch
            d.rectangle([ox, oy, ox + cw - 1, oy + ch - 1], outline=(120, 130, 150))
            sp, dx, dy = recortes[fid]
            im.paste(sp, (ox + dx, oy + dy), sp)
            d.line([ox + pvx - 9, oy + pvy, ox + pvx + 9, oy + pvy], fill=(255, 90, 90))
            d.line([ox + pvx, oy + pvy - 9, ox + pvx, oy + pvy + 9], fill=(255, 90, 90))
            d.text((ox + 4, oy + 3), fid, fill=(255, 220, 120))
    im.save(QA / "contacto.png")


def qa_onion(recortes, anim: str, cw: int, ch: int, pvx: float, pvy: float) -> None:
    """Todos los frames del ciclo superpuestos. Si el personaje deriva, se ve."""
    ids = next((i for a, i, *_ in ANIMS if a == anim), None)
    if not ids:
        return
    im = damero(cw, ch).convert("RGBA")
    for fid in ids:
        sp, dx, dy = recortes[fid]
        sp = sp.copy()
        sp.putalpha(sp.getchannel("A").point(lambda v: int(v * 0.30)))
        im.alpha_composite(sp, (dx, dy))
    d = ImageDraw.Draw(im)
    d.line([pvx - 12, pvy, pvx + 12, pvy], fill=(255, 90, 90, 255))
    d.line([pvx, pvy - 12, pvx, pvy + 12], fill=(255, 90, 90, 255))
    im.convert("RGB").save(QA / f"onion_{anim}.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    construir(ap.parse_args().report)
