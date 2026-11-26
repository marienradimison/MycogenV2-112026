// Test autonome de la passerelle (npm test) : faux MYCOGEN + faux automate, sur des ports de test.
'use strict';
const assert = require('assert');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

const P = { web: 18000, django: 18001, autoIn: 18200, autoOut: 18201 };
const cfgPath = path.join(os.tmpdir(), `mycogen-passerelle-test-${process.pid}.json`);
fs.writeFileSync(cfgPath, JSON.stringify({
  web: { ecoute_hote: '127.0.0.1', ecoute_port: P.web, cible_hote: '127.0.0.1', cible_port: P.django },
  automates: [{ nom: 'test', ecoute_port: P.autoIn, cible_port: P.autoOut }],
  journal: null,
}));

const big = Buffer.alloc(3 * 1024 * 1024, 'x');
const django = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const body = Buffer.concat(chunks);
    if (req.url === '/redirect') { res.writeHead(302, { Location: '/connexion/', 'Set-Cookie': ['a=1', 'b=2'] }); return res.end(); }
    if (req.url === '/gros') { res.writeHead(200); return res.end(big); }
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ method: req.method, url: req.url, host: req.headers.host,
      xff: req.headers['x-forwarded-for'], length: body.length, texte: 'Ã©chantillon' }));
  });
}).listen(P.django, '127.0.0.1');
const automate = net.createServer((s) => s.on('data', (d) => s.write(Buffer.concat([Buffer.from('ACK:'), d])))).listen(P.autoOut, '127.0.0.1');

function request(opts, body) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: P.web, ...opts }, (res) => {
      const c = []; res.on('data', (d) => c.push(d)); res.on('end', () => resolve({ res, body: Buffer.concat(c) }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

async function waitPort(port) {
  for (let i = 0; i < 50; i++) {
    const ok = await new Promise((r) => { const s = net.connect(port, '127.0.0.1', () => { s.end(); r(true); }); s.on('error', () => r(false)); });
    if (ok) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`port ${port} jamais ouvert`);
}

(async () => {
  const gw = spawn(process.execPath, [path.join(__dirname, 'passerelle.js')], {
    env: { ...process.env, MYCOGEN_PASSERELLE_CONFIG: cfgPath }, stdio: ['ignore', 'ignore', 'inherit'] });
  try {
    await waitPort(P.web); await waitPort(P.autoIn);

    let r = await request({ path: '/echantillons/?q=MYC26', headers: { Host: '192.0.2.89:8000' } });
    let j = JSON.parse(r.body.toString('utf8'));
    assert.strictEqual(j.url, '/echantillons/?q=MYC26');
    assert.strictEqual(j.host, '192.0.2.89:8000', 'en-tÃªte Host conservÃ© (ALLOWED_HOSTS / CSRF)');
    assert.strictEqual(j.xff, '127.0.0.1');
    assert.strictEqual(j.texte, 'Ã©chantillon');
    console.log('ok  GET, Host conservÃ©, X-Forwarded-For, UTF-8');

    r = await request({ method: 'POST', path: '/import/', headers: { 'Content-Type': 'application/octet-stream' } }, big);
    assert.strictEqual(JSON.parse(r.body).length, big.length);
    console.log('ok  POST 3 Mo (envoi de fichier)');

    r = await request({ path: '/gros' });
    assert.strictEqual(r.body.length, big.length);
    console.log('ok  tÃ©lÃ©chargement 3 Mo (export)');

    r = await request({ path: '/redirect' });
    assert.strictEqual(r.res.statusCode, 302);
    assert.strictEqual(r.res.headers.location, '/connexion/');
    assert.deepStrictEqual(r.res.headers['set-cookie'], ['a=1', 'b=2']);
    console.log('ok  redirection + plusieurs cookies (session/CSRF)');

    const reply = await new Promise((resolve, reject) => {
      const s = net.connect(P.autoIn, '127.0.0.1', () => s.write('\x05ENQ'));
      s.on('data', (d) => { resolve(d.toString()); s.end(); });
      s.on('error', reject);
    });
    assert.strictEqual(reply, 'ACK:\x05ENQ');
    console.log('ok  relais TCP automate');

    django.close(); django.closeAllConnections();
    await new Promise((r) => setTimeout(r, 200));
    r = await request({ path: '/' });
    assert.strictEqual(r.res.statusCode, 502);
    assert.ok(r.body.toString('utf8').includes('indisponible'));
    console.log('ok  page Â« indisponible Â» quand MYCOGEN est arrÃªtÃ©');
    console.log('\nTous les tests sont passÃ©s.');
  } catch (err) {
    console.error('Ã‰CHEC :', err.message);
    process.exitCode = 1;
  } finally {
    gw.kill(); fs.rmSync(cfgPath, { force: true });
    process.exit();
  }
})();
