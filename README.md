# AUSTRAL // PoC de movimiento — Kvothesson

### ▶ Jugalo acá: **[kvothesson.github.io/kvothesson-game](https://kvothesson.github.io/kvothesson-game/)**

Flechas o `A`/`D` para mover · `SHIFT` para correr · `ESPACIO` para saltar
(mantenerlo salta más alto) · `F1` debug · `L` banco de sprites.

---

Prueba de concepto de un side-scroller 2D con Kvothesson. El foco está en dos
cosas: que el **sprite sheet esté bien hecho** y que el **movimiento se sienta
bien**. No hay enemigos, ni niveles, ni colisiones: solo el personaje, el piso
y la cámara.

Es parte del universo **AUSTRAL**, donde el folklore argentino y la tecnología
post-singularidad colisionan. El fondo es la pampa de la Ruta 404: el campo
tiene píxeles muertos, y no conviene mirarlos fijo.

```
generate_sprites.py  ->  raw/*.png      23 frames sobre croma verde
build_sheet.py       ->  docs/*          sheet + atlas + QA
docs/index.html       ->  el juego
shots.js             ->  qa/juego_*.png capturas automatizadas
```

---

## 1. Cómo correrlo

```bash
python generate_sprites.py
```

```bash
python build_sheet.py
```

Después abrís `docs/index.html`. Anda por doble click (`file://`) y por
servidor local, porque el atlas se escribe también como `atlas.js`.

**Controles:** flechas o `A`/`D` para mover, `SHIFT` para correr, `ESPACIO`
para saltar (mantenerlo salta más alto), `F1` para el panel de debug, `L`
para el banco de sprites.

---

## 2. Los sprites

### El protocolo de anclaje

El problema real de armar un sprite sheet con IA no es dibujar bien: es que el
personaje **no cambie** entre frame y frame. Generado desde texto, cada llamada
te devuelve otro poncho, otra barba, otro largo de pelo, y la caminata vibra.

Por eso acá **una sola imagen se genera desde texto**: `K-BASE`, el idle neutro
de perfil. Los 22 frames restantes se generan adjuntando `K-BASE` como
referencia, con la instrucción de cambiar únicamente la pose. Es el mismo
protocolo que usa `production/el_uncido/`.

### El modelo del personaje va bloqueado

El canon deja el poncho **deliberadamente sin especificar** para que varíe entre
apariciones. Un sprite sheet no tolera eso: si el poncho cambia, el personaje
parpadea 12 veces por segundo.

Entonces para el juego se fija: **poncho índigo profundo con una banda
horizontal hueso cerca del borde**. Es una excepción consciente a la regla del
poncho variable, y aplica solo al build del juego. Los tres anclas de identidad
del canon sí se respetan textualmente en todos los frames: cola alta con
costados rapados, barba espesa de bordes precisos, cristal hexagonal en el
pecho.

### Los 23 frames

| Animación | Frames | Notas |
|---|---|---|
| `idle` | 4 | ciclo de respiración, el poncho deriva, el cristal late |
| `walk` | 8 | ciclo estándar contact / down / pass / up, x2 |
| `run` | 6 | contact / push off / aéreo, x2, torso inclinado |
| `jump` | 3 | despegue, apex recogido, caída con las piernas adelante |
| `land` | 1 | cuclillas profundas, una mano al piso |

Los frames espejados (`walk_04`..`walk_07`, `run_03`..`run_05`) se generan, no
se voltean por código: voltear la imagen daría vuelta al personaje.

### Regenerar un frame suelto

Si un frame sale mal, se regenera solo ese sin tocar los otros:

```bash
python generate_sprites.py --force walk_03
```

Y después `build_sheet.py` de nuevo. `--list` muestra el estado de los 23.

---

## 3. El armado del sheet

`build_sheet.py` es donde se arregla lo que la IA no puede garantizar. En orden
de importancia:

**1. Chroma key por componente conectada.** Se borra solo el verde que toca el
borde del cuadro. Un reflejo verdoso adentro del personaje no le abre un
agujero. Después hay despill para matar el halo ácido del contorno.

**2. Normalización de escala por ciclo.** El modelo dibuja al personaje un poco
más grande o más chico en cada llamada. Cada frame se lleva a la altura mediana
de su ciclo, con una **banda muerta del 4%** para no aplastar el rebote
vertical real de la caminata (que es parte de lo que la hace ver bien).

**3. Alineado por pivote, horneado en la celda.** En los frames apoyados el
pivote es el centroide horizontal de la banda de pies más la base del bounding
box. En los frames en el aire es el centroide del cuerpo, con una corrección
para las piernas recogidas del apex (`GROUND_LIFT`): sin eso, al recoger las
piernas el personaje parecería caerse de golpe. El pivote queda horneado en la
celda, así que el motor dibuja siempre la celda entera en la misma posición y
no necesita offsets por frame.

**4. Medición de zancada.** Se mide la apertura de piernas en el contact pose y
se guarda en el atlas como `cycleDistance`. Es lo que el motor usa para que el
pie no patine.

Ojo con esto, porque es un error fácil: el ancho de la banda de pies **no es el
paso**. Va de la punta del pie de atrás a la punta del de adelante, o sea el
paso *más un largo de bota*. La bota se mide del idle (pies juntos y de perfil,
la banda mide exactamente una bota) y se resta. Sin esa resta la zancada sale
231 px en vez de 168, un 37% de más — y como el motor deriva la velocidad de la
zancada, el personaje termina caminando demasiado rápido.

En la carrera la medida no sirve: el cuadro aéreo no apoya ningún pie. Ahí
`cycleDistance` sale de una fracción de la altura del personaje (1.45, que es
una zancada de carrera normal). El modo de cada animación está en `ZANCADA`.

### QA

`build_sheet.py` deja tres cosas en `qa/`:

- `contacto.png` — los 23 frames con su id, sobre damero, para revisar recortes
- `onion_walk.png`, `onion_run.png`, `onion_idle.png` — el ciclo entero
  superpuesto al 30%. Si el personaje deriva de escala o de posición, se ve de
  una.

`python build_sheet.py --report` mide y reporta sin escribir nada.

---

## 4. El movimiento

Lo que hace que se sienta bien no son los frames, es cómo se eligen:

**La caminata avanza por distancia recorrida, no por tiempo.** El atlas trae
cuánto mundo cubre un ciclo completo. La fase avanza `|vx| * dt /
cycleDistance`. Por eso el pie no patina ni acelerando ni frenando, y por eso
caminar y correr comparten la fase sin reiniciar el paso al cambiar.

**El salto se elige por velocidad vertical, no por tiempo.** Subiendo, apex,
cayendo. Un salto corto y uno largo leen distinto sin lógica extra.

**Ritmo.** Todo se lee mejor en alturas de personaje por segundo (ap/s), donde
el personaje mide 200 px. Un humano real camina a 0.8 ap/s y trota a 1.7:

| | velocidad | ciclos/s | cuadros/s | rampa al tope |
|---|---|---|---|---|
| caminar | 158 px/s · 0.79 ap/s | 0.94 | 7.5 | 0.18 s |
| correr | 385 px/s · 1.93 ap/s | 1.33 | 8.0 | 0.43 s |

El salto está en 178 px de apex y 0.91 s en el aire. La aceleración en piso es
900 px/s²: es el número que más se siente, porque define si el personaje
arranca con envión o sale disparado.

**Las ayudas clásicas de plataformas**, todas presentes:

| Ayuda | Valor | Para qué |
|---|---|---|
| coyote time | 0.10 s | saltar apenas después de salir del borde |
| jump buffer | 0.13 s | apretar salto un pelo antes de tocar el piso |
| salto variable | corte al 42% | soltar el botón corta la subida (46 px vs 178) |
| gravedad asimétrica | caída x1.40 | cae más rápido de lo que sube |
| colgada en el apex | x0.62 bajo 130 px/s | flota un instante arriba de todo |
| turn boost | acel. x2.2 | invertir el sentido responde al toque |
| histéresis walk/run | 45 px/s | no parpadea en el umbral |

**Timestep fijo a 120 Hz** con acumulador e interpolación al render: la física
no cambia con los FPS del monitor.

**Squash y stretch** en despegue y aterrizaje (con conservación de volumen),
sombra de contacto que se abre con la altura, polvo en frenos y caídas, y un
charco de luz ámbar del cristal hexagonal que late sobre el piso.

El fondo es la pampa de la Ruta 404 dibujada por código, con cinco capas de
parallax: banda de píxeles muertos en el horizonte, torres de servidores,
alambrado, pasto seco y niebla de datos a la altura del tobillo.

---

## 5. Verificación automatizada

El juego expone `window.__poc`, un puente que permite poner al personaje en un
estado concreto y pedir un cuadro sin depender de que alguien juegue a mano:

| Método | Qué hace |
|---|---|
| `pausar()` / `reanudar()` | frena el loop de rAF para que no contamine los tiempos |
| `avanzar(seg)` | corre la simulación esa cantidad de segundos, a paso fijo |
| `teclas([...])`, `saltar()`, `soltarSalto()` | inyecta entrada |
| `cuadro(t)` | dibuja un cuadro |
| `estado()`, `pantalla()` | estado de juego y posición en píxeles del canvas |

`shots.js` lo usa con Playwright para sacar las capturas de `qa/juego_*.png`,
incluida una tira de los 8 cuadros de la caminata:

```bash
node shots.js --tira
```

Falla con código distinto de cero si aparece cualquier error de consola.

---

## 6. Qué falta para que sea un juego

Esto es una PoC de movimiento. Lo que no está y sería el paso siguiente:

- Colisiones reales contra un tilemap (acá el piso es una constante)
- Plataformas, paredes, wall jump, dash
- Auri como compañera flotante (ya tiene canon visual completo)
- Un set de combate con Kvothesson en armadura tech-vikinga
- Ataques, hitboxes, cancels
