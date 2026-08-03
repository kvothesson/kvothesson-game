// Capturas automatizadas de la PoC. Usa el puente window.__poc para poner al
// personaje en un estado concreto y sacar la foto, sin depender de que alguien
// juegue a mano.
//
//   node shots.js            capturas sueltas
//   node shots.js --tira     ademas, una tira de 8 cuadros de la caminata
//
// Requiere el server local en 8795 (preview kvothesson-game-poc).
const { chromium } = require('D:/workspace/kvothesson/demo/node_modules/playwright');
const path = require('path');

const OUT = path.join(__dirname, 'qa');
const URL = 'http://localhost:8795/';

const ESCENAS = [
  ['01_idle', p => { p.teclas([]); p.avanzar(0.7); }],
  ['02_walk', p => { p.teclas(['arrowright']); p.avanzar(1.35); }],
  ['03_run', p => { p.teclas(['arrowright', 'shift']); p.avanzar(2.1); }],
  // El salto dura 0.91s en el aire, asi que los cortes van repartidos ahi.
  ['04_jump_sube', p => { p.teclas(['arrowright', 'shift']); p.avanzar(1.6); p.saltar(); p.avanzar(0.18); }],
  ['05_jump_apex', p => { p.teclas(['arrowright', 'shift']); p.avanzar(1.6); p.saltar(); p.avanzar(0.46); }],
  ['06_jump_cae', p => { p.teclas(['arrowright', 'shift']); p.avanzar(1.6); p.saltar(); p.avanzar(0.78); }],
  ['07_aterriza', p => { p.teclas(['arrowright', 'shift']); p.avanzar(1.6); p.saltar(); p.avanzar(0.94); }],
  ['08_salto_corto', p => { p.teclas([]); p.saltar(); p.avanzar(0.06); p.soltarSalto(); p.avanzar(0.20); }],
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
  const errores = [];
  page.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
  page.on('pageerror', e => errores.push(String(e)));

  await page.goto(URL, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.__poc && window.__poc.listo, null, { timeout: 15000 });
  await page.evaluate(() => window.__poc.pausar());

  for (const [nombre, guion] of ESCENAS) {
    await page.evaluate(({ src }) => {
      window.__poc.reset();
      // eslint-disable-next-line no-new-func
      new Function('p', src)(window.__poc);
      window.__poc.cuadro(2.0);
    }, { src: '(' + guion.toString() + ')(p)' });
    await page.screenshot({ path: path.join(OUT, `juego_${nombre}.png`) });
    const st = await page.evaluate(() => window.__poc.estado());
    console.log(nombre.padEnd(14), JSON.stringify(st));
  }

  if (process.argv.includes('--tira')) {
    // Tira de un ciclo completo, un recorte por cuadro de animacion, para ver
    // el ciclo entero dentro del juego sin tener que jugarlo.
    for (const anim of ['walk', 'run']) {
      await page.evaluate((anim) => {
        const A = window.ATLAS.anims[anim];
        const c = document.getElementById('c');
        const out = document.createElement('canvas');
        out.width = 200 * A.frames; out.height = 400;
        const o = out.getContext('2d');
        window.__poc.reset();
        window.__poc.teclas(anim === 'run' ? ['arrowright', 'shift'] : ['arrowright']);
        window.__poc.avanzar(2.0);                     // llegar al tope
        const vx = window.__poc.estado().vx;
        for (let i = 0; i < A.frames; i++) {
          window.__poc.cuadro(2 + i * 0.1);
          // La camara sigue al personaje, asi que el recorte tiene que ir a
          // buscarlo a donde quedo en pantalla, no a un rectangulo fijo.
          const p = window.__poc.pantalla();
          o.drawImage(c, p.x - 100, p.y - 320, 200, 400, i * 200, 0, 200, 400);
          window.__poc.avanzar(A.cycleDistance / vx / A.frames);   // 1/N de ciclo
        }
        let a = document.getElementById('__tira');
        if (!a) { a = document.createElement('a'); a.id = '__tira'; document.body.appendChild(a); }
        a.href = out.toDataURL('image/png');
      }, anim);
      const data = await page.evaluate(() => document.getElementById('__tira').href);
      require('fs').writeFileSync(path.join(OUT, `juego_tira_${anim}.png`),
        Buffer.from(data.split(',')[1], 'base64'));
      console.log('tira      ', `qa/juego_tira_${anim}.png`);
    }
  }

  await browser.close();
  if (errores.length) {
    console.log('\nERRORES DE CONSOLA:');
    errores.forEach(e => console.log('  ' + e));
    process.exit(1);
  }
  console.log('\nsin errores de consola');
})();
