// AUSTRAL // PoC de movimiento - Kvothesson
//
// Motor 2D minimo pero con el "game feel" completo. Lo que hace que el
// movimiento se sienta bien, en orden de importancia:
//
//  1. La animacion de caminar avanza por DISTANCIA RECORRIDA, no por tiempo.
//     El atlas trae cuanto mundo cubre un ciclo completo, medido de la
//     apertura de piernas del sprite. Por eso el pie no patina sobre el piso
//     ni acelerando ni frenando.
//  2. La animacion de salto se elige por VELOCIDAD VERTICAL, no por tiempo.
//     Subiendo, apex, cayendo. Un salto corto y uno largo leen distinto solos.
//  3. Coyote time, jump buffer, salto de altura variable y gravedad asimetrica
//     (se cae mas rapido de lo que se sube, y flota un poco en el apex).
//  4. Timestep fijo a 120 Hz con interpolacion al render. La fisica no cambia
//     con los FPS del monitor.
//  5. Squash y stretch en el despegue y el aterrizaje, sombra de contacto que
//     se abre con la altura, y polvo en los frenos y las caidas.

(() => {
  'use strict';

  const cv = document.getElementById('c');
  const ctx = cv.getContext('2d', { alpha: false });
  const dbgEl = document.getElementById('dbg');
  const errEl = document.getElementById('err');

  // ---------------------------------------------------------------- ajustes
  const VIEW_H = 760;          // altura logica del mundo, en unidades = px sprite
  const GROUND_FRAC = 0.80;    // donde cae la linea de piso en pantalla

  // Las velocidades salen del atlas, no se eligen a ojo. El personaje mide
  // 200px, asi que todo se lee en alturas de personaje por segundo (ap/s):
  //   walk.cycleDistance = 168px  ->  158 px/s son 0.94 ciclos/s, 0.79 ap/s
  //   run.cycleDistance  = 290px  ->  385 px/s son 1.33 ciclos/s, 1.93 ap/s
  // Un humano real camina a 0.8 ap/s y trota a 1.7 ap/s, asi que esto queda
  // apenas por encima de lo natural, que es lo que se busca en un juego.
  const K = {
    walkMax: 158,
    runMax: 385,
    // La aceleracion es lo que mas se siente. A 2400 llegaba al tope en 0.1s
    // y eso lee como un personaje disparado. A 900 tarda 0.18s en caminata y
    // 0.43s en carrera: se ve el envion.
    accGround: 900,
    accAir: 650,
    turnBoost: 2.2,            // acelera mas rapido cuando invierte el sentido
    fricGround: 1400,          // frena con un resto de patinada, no de golpe
    fricAir: 220,
    // Gravedad y salto bajaron juntos para conservar el apex en ~180px y
    // alargar el tiempo en el aire de 0.55s a 0.85s.
    gravity: 1750,
    fallMul: 1.40,             // cae mas rapido de lo que sube
    apexMul: 0.62,             // flota un instante arriba de todo
    apexBand: 130,
    jumpV: 790,                // apex ~178px, cerca de la altura del personaje
    cutMul: 0.42,              // soltar espacio corta el salto
    coyote: 0.10,
    buffer: 0.13,
    runGate: 250,              // arriba de esto se usa el ciclo de carrera
    landHard: 480,             // caida que dispara la pose de aterrizaje
    landTime: 0.17,
  };

  const DT = 1 / 120;

  // ---------------------------------------------------------------- entrada
  const keys = new Set();
  let jumpPressedAt = -99, jumpHeld = false;
  let showDbg = false, showLab = false;

  addEventListener('keydown', e => {
    if (e.repeat) return;
    const k = e.key.toLowerCase();
    keys.add(k);
    if (k === ' ' || k === 'arrowup' || k === 'w') {
      jumpPressedAt = now; jumpHeld = true; e.preventDefault();
    }
    if (e.key === 'F1') { showDbg = !showDbg; dbgEl.style.display = showDbg ? 'block' : 'none'; e.preventDefault(); }
    if (k === 'l') showLab = !showLab;
  });
  addEventListener('keyup', e => {
    const k = e.key.toLowerCase();
    keys.delete(k);
    if (k === ' ' || k === 'arrowup' || k === 'w') jumpHeld = false;
  });
  addEventListener('blur', () => { keys.clear(); jumpHeld = false; });

  const axis = () => (keys.has('arrowright') || keys.has('d') ? 1 : 0) -
                     (keys.has('arrowleft') || keys.has('a') ? 1 : 0);
  const running = () => keys.has('shift');

  // ---------------------------------------------------------------- estado
  const P = {
    x: 0, y: 0, vx: 0, vy: 0,
    dir: 1, grounded: true, groundedAt: 0,
    anim: 'idle', phase: 0, timeIn: 0,
    landT: 0, squash: 1,
  };
  let prev = { x: 0, y: 0 };
  let cam = 0, camTarget = 0;
  let camX = 0;          // borde izquierdo del encuadre, derivado de cam
  const dust = [];
  let now = 0;

  // ---------------------------------------------------------------- fisica
  function step(dt) {
    const ax = axis();
    const grounded = P.grounded;

    // --- horizontal
    const max = running() ? K.runMax : K.walkMax;
    if (ax !== 0) {
      if (ax !== P.dir && Math.abs(P.vx) > 130 && grounded) puff(P.x, 0, -P.dir, 5);
      P.dir = ax;
      let acc = grounded ? K.accGround : K.accAir;
      if (Math.sign(P.vx) !== 0 && Math.sign(P.vx) !== ax) acc *= K.turnBoost;
      if (P.landT > 0) acc *= 0.45;
      P.vx += ax * acc * dt;
      // el tope solo frena, nunca acelera: venir de correr y soltar shift
      // desacelera suave en vez de cortar de golpe
      if (Math.abs(P.vx) > max) {
        P.vx -= Math.sign(P.vx) * Math.min(Math.abs(P.vx) - max, K.fricGround * dt);
      }
    } else {
      const f = (grounded ? K.fricGround : K.fricAir) * dt;
      P.vx = Math.abs(P.vx) <= f ? 0 : P.vx - Math.sign(P.vx) * f;
    }

    // --- salto
    const canCoyote = now - P.groundedAt < K.coyote;
    const buffered = now - jumpPressedAt < K.buffer;
    if (buffered && (grounded || canCoyote)) {
      P.vy = -K.jumpV;
      P.grounded = false;
      jumpPressedAt = -99;
      P.groundedAt = -99;
      puff(P.x, 0, 0, 4);
    }
    if (!jumpHeld && P.vy < 0) P.vy *= Math.pow(K.cutMul, dt * 60);

    // --- gravedad asimetrica con colgada en el apex
    if (!P.grounded) {
      let g = K.gravity;
      if (P.vy > 0) g *= K.fallMul;
      if (Math.abs(P.vy) < K.apexBand) g *= K.apexMul;
      P.vy += g * dt;
    }

    P.x += P.vx * dt;
    P.y += P.vy * dt;

    // --- piso
    if (P.y >= 0) {
      if (!P.grounded) {
        if (P.vy > K.landHard) { P.landT = K.landTime; puff(P.x, 0, 0, 10); }
        else if (P.vy > 200) puff(P.x, 0, 0, 3);
      }
      P.y = 0; P.vy = 0; P.grounded = true; P.groundedAt = now;
    } else {
      P.grounded = false;
    }
    if (P.landT > 0) P.landT -= dt;

    elegirAnim(dt);

    // --- squash / stretch
    let target = 1;
    if (!P.grounded) target = 1 + Math.min(Math.abs(P.vy) * 0.00012, 0.11);
    else if (P.landT > 0) target = 0.80 + 0.20 * (1 - P.landT / K.landTime);
    P.squash += (target - P.squash) * Math.min(1, dt * 22);

    for (let i = dust.length - 1; i >= 0; i--) {
      const p = dust[i];
      p.t += dt; p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 260 * dt;
      if (p.t > p.life) dust.splice(i, 1);
    }

    // La camara es estado de juego, no de dibujo: se integra en el paso fijo.
    // Si se actualiza en el render, con el loop pausado se queda colgada y
    // ademas su suavizado dependeria de los FPS.
    camTarget = P.x + P.vx * 0.20;
    cam += (camTarget - cam) * Math.min(1, dt * 3.2);
  }

  // La eleccion de animacion es todo el "juego se ve bien". Nada aca depende
  // de un timer: depende de la velocidad real del personaje.
  function elegirAnim(dt) {
    const A = ATLAS.anims;
    let next;
    if (!P.grounded) {
      next = 'jump';
    } else if (P.landT > 0) {
      next = 'land';
    } else if (Math.abs(P.vx) < 14) {
      next = 'idle';
    } else {
      // histeresis para que no parpadee entre caminar y correr en el limite
      const gate = P.anim === 'run' ? K.runGate - 45 : K.runGate;
      next = Math.abs(P.vx) > gate ? 'run' : 'walk';
    }
    if (next !== P.anim) {
      // caminar y correr comparten la fase: el cambio no reinicia el paso
      if (!(next === 'run' && P.anim === 'walk') && !(next === 'walk' && P.anim === 'run')) P.phase = 0;
      P.anim = next; P.timeIn = 0;
    }
    P.timeIn += dt;

    if (next === 'walk' || next === 'run') {
      // AVANCE POR DISTANCIA: esto es lo que elimina el patinaje del pie
      P.phase += Math.abs(P.vx) * dt / A[next].cycleDistance;
    } else if (next === 'idle') {
      P.phase += dt * A.idle.fps / A.idle.frames;
    }
  }

  function frameActual() {
    const A = ATLAS.anims[P.anim];
    if (P.anim === 'jump') {
      // POR VELOCIDAD, no por tiempo: subiendo / apex / cayendo
      if (P.vy < -190) return 0;
      if (P.vy < 190) return 1;
      return 2;
    }
    if (P.anim === 'land') return 0;
    return Math.floor(P.phase * A.frames) % A.frames;
  }

  function puff(x, y, dir, n) {
    for (let i = 0; i < n; i++) {
      dust.push({
        x: x + (Math.random() - 0.5) * 26,
        y: y - Math.random() * 8,
        vx: (dir || (Math.random() < 0.5 ? -1 : 1)) * (35 + Math.random() * 120),
        vy: -30 - Math.random() * 90,
        r: 4 + Math.random() * 9,
        t: 0, life: 0.35 + Math.random() * 0.35,
      });
    }
  }

  // ---------------------------------------------------------------- fondo
  // Pampa de la Ruta 404: banda de pixeles muertos en el horizonte, torres de
  // servidores lejanas, postes de alambrado y niebla de datos a la altura del
  // tobillo. Todo dibujado por codigo y con parallax.
  const hash = n => { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); };

  function fondo(w, h, gy) {
    const cielo = ctx.createLinearGradient(0, 0, 0, gy);
    cielo.addColorStop(0, '#070a18');
    cielo.addColorStop(0.55, '#0d1830');
    cielo.addColorStop(0.88, '#183048');
    cielo.addColorStop(1, '#22415a');
    ctx.fillStyle = cielo;
    ctx.fillRect(0, 0, w, gy);

    // luna
    const mx = w * 0.76 - camX * 0.02, my = gy * 0.24;
    const luna = ctx.createRadialGradient(mx, my, 18, mx, my, 130);
    luna.addColorStop(0, 'rgba(180,215,250,0.20)');
    luna.addColorStop(1, 'rgba(180,215,250,0)');
    ctx.fillStyle = luna; ctx.beginPath(); ctx.arc(mx, my, 130, 0, 7); ctx.fill();
    ctx.fillStyle = 'rgba(214,228,244,0.92)';
    ctx.beginPath(); ctx.arc(mx, my, 26, 0, 7); ctx.fill();

    // banda de pixeles muertos (Ruta 404)
    const p1 = camX * 0.08;
    ctx.save();
    for (let i = -2; i < 46; i++) {
      const wx = Math.floor((p1 / 90) + i) * 90;
      const sx = wx - p1;
      if (sx > w + 90 || sx < -140) continue;
      const s = hash(wx);
      if (s > 0.55) continue;
      const bw = 26 + s * 120, bh = 12 + hash(wx + 7) * 46;
      const by = gy * 0.30 + hash(wx + 3) * gy * 0.22;
      ctx.fillStyle = hash(wx + 11) > 0.72 ? 'rgba(46,84,96,0.75)' : 'rgba(24,34,52,0.85)';
      ctx.fillRect(sx, by, bw, bh);
    }
    ctx.restore();

    // torres de servidores lejanas. Ralas: la pampa es vacio, no skyline.
    const p2 = camX * 0.20;
    for (let i = -2; i < 40; i++) {
      const wx = Math.floor((p2 / 210) + i) * 210;
      const sx = wx - p2;
      if (sx > w + 210 || sx < -260) continue;
      const s = hash(wx * 0.7);
      if (s > 0.40) continue;
      const tw = 26 + s * 80, th = 70 + hash(wx + 5) * 320;
      ctx.fillStyle = '#091220';
      ctx.fillRect(sx, gy - th, tw, th);
      // antena y baliza
      ctx.fillRect(sx + tw * 0.5 - 1, gy - th - 26 - s * 40, 2, 26 + s * 40);
      ctx.fillStyle = 'rgba(255,90,80,0.55)';
      ctx.fillRect(sx + tw * 0.5 - 2, gy - th - 28 - s * 40, 4, 4);
      for (let r = 0; r < th / 26; r++) {
        if (hash(wx + r * 13) > 0.5) continue;
        ctx.fillStyle = hash(wx + r) > 0.5 ? 'rgba(110,205,240,0.45)' : 'rgba(255,175,90,0.38)';
        ctx.fillRect(sx + 6 + (r % 2) * (tw - 18), gy - th + 14 + r * 26, 6, 4);
      }
    }

    // horizonte
    ctx.fillStyle = 'rgba(10,20,34,0.9)';
    ctx.fillRect(0, gy - 14, w, 14);

    // piso. No puede quedar casi negro: sobre negro la sombra de contacto no
    // se ve, y sin sombra el personaje flota.
    const suelo = ctx.createLinearGradient(0, gy, 0, h);
    suelo.addColorStop(0, '#25333c');
    suelo.addColorStop(0.35, '#1a252d');
    suelo.addColorStop(1, '#0b1117');
    ctx.fillStyle = suelo;
    ctx.fillRect(0, gy, w, h - gy);
    ctx.strokeStyle = 'rgba(140,200,230,0.22)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, gy + 1); ctx.lineTo(w, gy + 1); ctx.stroke();

    // postes de alambrado, plano medio
    const p3 = camX * 0.55;
    ctx.strokeStyle = 'rgba(150,190,210,0.16)'; ctx.lineWidth = 1;
    for (let i = -2; i < 26; i++) {
      const wx = Math.floor((p3 / 260) + i) * 260;
      const sx = wx - p3;
      if (sx > w + 260 || sx < -260) continue;
      ctx.fillStyle = '#0c161e';
      ctx.fillRect(sx, gy - 96, 7, 96);
      ctx.beginPath();
      ctx.moveTo(sx, gy - 88); ctx.quadraticCurveTo(sx + 130, gy - 74, sx + 260, gy - 88);
      ctx.moveTo(sx, gy - 62); ctx.quadraticCurveTo(sx + 130, gy - 48, sx + 260, gy - 62);
      ctx.stroke();
    }

    // pasto seco. Dos bandas: una atras de la linea de piso y otra adelante,
    // ambas 1:1 con el mundo. Ralo y desparejo, si no lee como empalizada.
    for (const [paso, dy, alfa, largo] of [[23, -7, 0.13, 16], [19, 9, 0.20, 26]]) {
      for (let i = -2; i < 140; i++) {
        const wx = Math.floor((camX / paso) + i) * paso;
        const sx = wx - camX;
        if (sx > w + paso || sx < -paso) continue;
        const s = hash(wx * 1.3), s2 = hash(wx * 2.7);
        if (s2 > 0.62) continue;                       // huecos
        const base = gy + dy + s2 * 6;
        const alto = largo * (0.35 + s);
        ctx.strokeStyle = `rgba(96,126,116,${alfa * (0.5 + s)})`;
        ctx.lineWidth = 1 + s;
        ctx.beginPath();
        ctx.moveTo(sx, base);
        ctx.quadraticCurveTo(sx + (s - 0.5) * 5, base - alto * 0.6,
                             sx + (s - 0.5) * 17, base - alto);
        ctx.stroke();
      }
    }

    // vinieta
    const vg = ctx.createRadialGradient(w / 2, gy * 0.62, gy * 0.35, w / 2, gy * 0.62, w * 0.72);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,0.34)');
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);
  }

  function niebla(w, gy, t) {
    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    for (let i = 0; i < 3; i++) {
      const off = (camX * (0.3 + i * 0.12) + t * (7 + i * 5)) % 420;
      const g = ctx.createLinearGradient(0, gy - 44 + i * 10, 0, gy + 16);
      g.addColorStop(0, 'rgba(90,140,170,0)');
      g.addColorStop(0.6, `rgba(70,120,160,${0.07 - i * 0.015})`);
      g.addColorStop(1, 'rgba(60,110,150,0)');
      ctx.fillStyle = g;
      ctx.fillRect(-off, gy - 50 + i * 10, w + 840, 70);
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------- sprite
  const sheet = new Image();
  let listo = false;
  sheet.onload = () => { listo = true; };
  sheet.onerror = () => {
    errEl.style.display = 'grid';
    errEl.textContent = 'Falta web/kvothesson.png. Genera los frames con generate_sprites.py y arma el sheet con build_sheet.py.';
  };
  if (typeof ATLAS === 'undefined') {
    errEl.style.display = 'grid';
    errEl.textContent = 'Falta web/atlas.js. Corre build_sheet.py.';
  } else {
    sheet.src = ATLAS.image;
  }

  function dibujarPersonaje(sx, sy) {
    const { w: cw, h: ch } = ATLAS.cell;
    const { x: pvx, y: pvy } = ATLAS.pivot;
    const row = ATLAS.anims[P.anim].row;
    const col = frameActual();

    const sy2 = P.squash;
    const sx2 = 1 / Math.sqrt(sy2);   // conserva volumen

    ctx.save();
    ctx.translate(sx, sy);
    ctx.scale(P.dir * sx2, sy2);
    ctx.drawImage(sheet, col * cw, row * ch, cw, ch, -pvx, -pvy, cw, ch);
    ctx.restore();
  }

  function sombra(sx, gyScreen, alturaSobreSuelo) {
    const k = Math.max(0, 1 - alturaSobreSuelo / 340);
    ctx.save();
    ctx.translate(sx, gyScreen + 3);
    ctx.scale(1, 0.26);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 62);
    g.addColorStop(0, `rgba(0,0,0,${0.52 * k + 0.08})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(0, 0, 62 * (0.55 + k * 0.45), 0, 7); ctx.fill();
    ctx.restore();
  }

  function charcoDeLuz(sx, gyScreen, t) {
    // El cristal hexagonal del pecho tira ambar sobre el piso. Late.
    const pulso = 0.72 + 0.28 * Math.sin(t * 2.1);
    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    ctx.translate(sx, gyScreen + 2);
    ctx.scale(1, 0.3);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 110);
    g.addColorStop(0, `rgba(255,176,74,${0.20 * pulso})`);
    g.addColorStop(1, 'rgba(255,176,74,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(0, 0, 110, 0, 7); ctx.fill();
    ctx.restore();
  }

  // Banco de sprites: cicla cada animacion en el lugar, con la cruz del
  // pivote. Sirve para juzgar el sheet sin jugar.
  function bancoDeSprites(w, h, t) {
    const { w: cw, h: ch } = ATLAS.cell;
    const { x: pvx, y: pvy } = ATLAS.pivot;
    ctx.save();
    ctx.fillStyle = 'rgba(4,6,12,0.9)';
    ctx.fillRect(0, 0, w, h);
    const nombres = Object.keys(ATLAS.anims);
    const esc = Math.min(1, (w / nombres.length) / (cw * 1.15), (h * 0.72) / ch);
    nombres.forEach((n, i) => {
      const A = ATLAS.anims[n];
      const f = Math.floor(t * A.fps) % A.frames;
      const ox = (w / nombres.length) * (i + 0.5);
      const oy = h * 0.80;
      ctx.save();
      ctx.translate(ox, oy); ctx.scale(esc, esc);
      ctx.drawImage(sheet, f * cw, A.row * ch, cw, ch, -pvx, -pvy, cw, ch);
      ctx.strokeStyle = 'rgba(255,120,120,0.9)'; ctx.lineWidth = 1 / esc;
      ctx.beginPath();
      ctx.moveTo(-14 / esc, 0); ctx.lineTo(14 / esc, 0);
      ctx.moveTo(0, -14 / esc); ctx.lineTo(0, 14 / esc);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(120,180,220,0.28)';
      ctx.strokeRect(-pvx, -pvy, cw, ch);
      ctx.restore();
      ctx.fillStyle = '#ffd08a'; ctx.font = '13px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(`${n}  ${f + 1}/${A.frames}`, ox, h * 0.88);
    });
    ctx.textAlign = 'left';
    ctx.fillStyle = '#9fb4cc'; ctx.font = '12px ui-monospace, monospace';
    ctx.fillText('BANCO DE SPRITES — L para volver al juego. La cruz roja es el pivote horneado en la celda.', 16, 26);
    ctx.restore();
  }

  // ---------------------------------------------------------------- loop
  let acc = 0, last = performance.now() / 1000;
  let ultimoCuadro = null;   // geometria del ultimo render, la usa el puente

  function simular(dt) {
    acc += dt;
    while (acc >= DT) {
      prev.x = P.x; prev.y = P.y;
      now += DT;
      step(DT);
      acc -= DT;
    }
  }

  let pausado = false;

  function loop(ms) {
    requestAnimationFrame(loop);
    const t = ms / 1000;
    let dt = Math.min(t - last, 0.25);
    last = t;
    if (!listo || pausado) return;
    simular(dt);
    render(t, dt);
  }

  function render(t, dt) {
    const alpha = acc / DT;
    const ix = prev.x + (P.x - prev.x) * alpha;
    const iy = prev.y + (P.y - prev.y) * alpha;

    // --- viewport
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== (W * dpr | 0) || cv.height !== (H * dpr | 0)) {
      cv.width = W * dpr | 0; cv.height = H * dpr | 0;
    }
    const esc = (H * dpr) / VIEW_H;
    ctx.setTransform(esc, 0, 0, esc, 0, 0);
    const vw = (W * dpr) / esc, vh = VIEW_H;
    const gy = vh * GROUND_FRAC;

    // cam guarda el punto de mira en el mundo; el encuadre se centra en el
    camX = cam - vw * 0.5;

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ultimoCuadro = { esc, vw, vh, gy, sx: ix - camX, sy: gy + iy };

    if (showLab) { bancoDeSprites(vw, vh, t); dbg(dt); return; }

    fondo(vw, vh, gy);

    const sx = ix - camX;
    const sy = gy + iy;

    charcoDeLuz(sx, gy, t);
    sombra(sx, gy, -iy);

    for (const p of dust) {
      const a = 1 - p.t / p.life;
      const rr = p.r * (1 + (1 - a) * 1.8);
      const px = p.x - camX, py = gy + p.y;
      const g = ctx.createRadialGradient(px, py, 0, px, py, rr);
      g.addColorStop(0, `rgba(180,198,196,${0.20 * a * a})`);
      g.addColorStop(1, 'rgba(180,198,196,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(px, py, rr, 0, 7); ctx.fill();
    }

    dibujarPersonaje(sx, sy);
    niebla(vw, gy, t);
    dbg(dt);
  }

  // Puente de prueba. Permite correr la simulacion y pedir un cuadro sin
  // depender de requestAnimationFrame, que no dispara si la pestana no
  // compone. Se usa para verificar el movimiento de forma automatizada.
  window.__poc = {
    get listo() { return listo; },
    // Sin esto el loop de rAF sigue simulando entre llamadas del puente y los
    // tiempos medidos salen mal.
    pausar: () => { pausado = true; },
    reanudar: () => { pausado = false; last = performance.now() / 1000; },
    estado: () => ({ anim: P.anim, frame: frameActual(), x: +P.x.toFixed(1),
                     y: +P.y.toFixed(1), vx: +P.vx.toFixed(1), vy: +P.vy.toFixed(1),
                     dir: P.dir, piso: P.grounded, fase: +(P.phase % 1).toFixed(3),
                     squash: +P.squash.toFixed(3) }),
    teclas: (arr) => { keys.clear(); (arr || []).forEach(k => keys.add(k)); },
    saltar: () => { jumpPressedAt = now; jumpHeld = true; },
    soltarSalto: () => { jumpHeld = false; },
    avanzar: (seg) => { for (let i = 0; i < Math.round(seg / DT); i++) { now += DT; prev.x = P.x; prev.y = P.y; step(DT); } },
    cuadro: (t) => { acc = 0; render(t || 0, 1 / 60); },
    // posicion del personaje en pixeles reales del canvas, para recortar
    pantalla: () => ultimoCuadro && ({ x: ultimoCuadro.sx * ultimoCuadro.esc,
                                       y: ultimoCuadro.sy * ultimoCuadro.esc,
                                       piso: ultimoCuadro.gy * ultimoCuadro.esc,
                                       esc: ultimoCuadro.esc }),
    reset: () => { Object.assign(P, { x: 0, y: 0, vx: 0, vy: 0, dir: 1, grounded: true, anim: 'idle', phase: 0, landT: 0, squash: 1 }); cam = P.x; camX = 0; },
  };

  function dbg(dt) {
    if (!showDbg) return;
    const A = ATLAS.anims[P.anim];
    dbgEl.textContent = [
      `fps      ${(1 / Math.max(dt, 1e-4)).toFixed(0)}`,
      `estado   ${P.anim}  frame ${frameActual() + 1}/${A.frames}`,
      `vel      vx ${P.vx.toFixed(0).padStart(5)}  vy ${P.vy.toFixed(0).padStart(5)}`,
      `pos      x ${P.x.toFixed(0)}  altura ${(-P.y).toFixed(0)}`,
      `piso     ${P.grounded ? 'si' : 'no '}   dir ${P.dir > 0 ? '>' : '<'}`,
      `ciclo    ${A.cycleDistance}px   fase ${(P.phase % 1).toFixed(2)}`,
      `squash   ${P.squash.toFixed(3)}`,
      `celda    ${ATLAS.cell.w}x${ATLAS.cell.h}  pivote ${ATLAS.pivot.x},${ATLAS.pivot.y}`,
    ].join('\n');
  }

  requestAnimationFrame(loop);
})();
