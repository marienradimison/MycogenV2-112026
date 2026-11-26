#!/usr/bin/env node
/*
 * MYCOGEN V2 â€” passerelle rÃ©seau Node.js (Windows).
 *
 * Pourquoi : MYCOGEN V2 (Django) tourne dans WSL2/Ubuntu. Le pare-feu Windows / Hyper-V bloque les
 * connexions des autres PC vers WSL, et nous n'avons pas les droits administrateur pour ajouter une rÃ¨gle.
 * En revanche, node.exe est dÃ©jÃ  autorisÃ© (MYCOGEN V1 fonctionne avec Â« npm start Â»).
 *
 * Cette passerelle, lancÃ©e avec node sous Windows, Ã©coute sur le rÃ©seau et relaie chaque requÃªte vers
 * MYCOGEN qui n'Ã©coute qu'en local (http://127.0.0.1:8001 dans WSL). Aucune dÃ©pendance npm.
 *
 *   npm start                (ou : node passerelle.js)
 *
 * RÃ©glages : config.json (mÃªme dossier).
 */
'use strict';

const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

const DIR = __dirname;
const CONFIG_FILE = process.env.MYCOGEN_PASSERELLE_CONFIG || path.join(DIR, 'config.json');
const DEFAULTS = {
  web: { ecoute_hote: '0.0.0.0', ecoute_port: 8000, cible_hote: '127.0.0.1', cible_port: 8001 },
  automates: [],
  journal: 'logs/passerelle.log',
};

function loadConfig() {
  let user = {};
  if (fs.existsSync(CONFIG_FILE)) {
    try {
      user = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8').replace(/^ï»¿/, ''));
    } catch (err) {
      console.error(`config.json illisible : ${err.message}`);
      process.exit(1);
    }
  }
  return {
    web: { ...DEFAULTS.web, ...(user.web || {}) },
    automates: Array.isArray(user.automates) ? user.automates : DEFAULTS.automates,
    journal: user.journal === undefined ? DEFAULTS.journal : user.journal,
  };
}

const config = loadConfig();

// ---------------------------------------------------------------------------- journal
let logStream = null;
if (config.journal) {
  const logPath = path.resolve(DIR, config.journal);
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  try {
    // Rotation simple : au-delÃ  de 5 Mo, l'ancien journal devient .1
    if (fs.existsSync(logPath) && fs.statSync(logPath).size > 5 * 1024 * 1024) {
      fs.renameSync(logPath, logPath + '.1');
    }
  } catch (_) { /* journal verrouillÃ© : on continue */ }
  logStream = fs.createWriteStream(logPath, { flags: 'a' });
}

function log(message) {
  const line = `${new Date().toLocaleString('fr-FR')}  ${message}`;
  console.log(line);
  if (logStream) logStream.write(line + os.EOL);
}

// ---------------------------------------------------------------------------- web (HTTP)
const HOP_BY_HOP = new Set(['connection', 'keep-alive', 'proxy-connection', 'transfer-encoding',
  'te', 'trailer', 'upgrade', 'proxy-authorization', 'proxy-authenticate']);

const agent = new http.Agent({ keepAlive: true, maxSockets: 64 });
const web = config.web;

function clientIp(reqOrSocket) {
  const socket = reqOrSocket.socket || reqOrSocket;
  return (socket.remoteAddress || '').replace(/^::ffff:/, '');
}

function forwardedHeaders(req) {
  const headers = {};
  for (const [name, value] of Object.entries(req.headers)) {
    if (!HOP_BY_HOP.has(name)) headers[name] = value;
  }
  const ip = clientIp(req);
  headers['x-forwarded-for'] = ip;
  headers['x-forwarded-proto'] = 'http';
  if (req.headers.host) headers['x-forwarded-host'] = req.headers.host;
  return headers;
}

const UNAVAILABLE_PAGE = `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15"><title>MYCOGEN indisponible</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;color:#222}
h1{color:#8a1c1c}code{background:#f2f2f2;padding:.1rem .3rem}</style></head><body>
<h1>MYCOGEN est momentanÃ©ment indisponible</h1>
<p>Le serveur MYCOGEN (Ubuntu / WSL) ne rÃ©pond pas encore. Il est peut-Ãªtre en cours de dÃ©marrage :
cette page se recharge toute seule dans 15 secondes.</p>
<p>Si le problÃ¨me persiste, prÃ©venir la personne responsable du serveur.</p>
</body></html>`;

function sendUnavailable(res, err) {
  log(`web : MYCOGEN injoignable sur ${web.cible_hote}:${web.cible_port} (${err.code || err.message})`);
  if (res.headersSent) { res.destroy(); return; }
  res.writeHead(502, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(UNAVAILABLE_PAGE);
}

const server = http.createServer((req, res) => {
  const upstream = http.request({
    host: web.cible_hote,
    port: web.cible_port,
    method: req.method,
    path: req.url,
    headers: forwardedHeaders(req),
    agent,
  }, (upRes) => {
    const headers = {};
    for (const [name, value] of Object.entries(upRes.headers)) {
      if (!HOP_BY_HOP.has(name)) headers[name] = value;
    }
    res.writeHead(upRes.statusCode, upRes.statusMessage, headers);
    upRes.pipe(res);
    upRes.on('error', () => res.destroy());
  });
  upstream.on('error', (err) => sendUnavailable(res, err));
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => { if (!res.writableFinished) upstream.destroy(); });
  req.pipe(upstream);
});

// Imports et exports volumineux : pas de limite de durÃ©e sur une requÃªte (Node coupe Ã  5 min par dÃ©faut).
server.requestTimeout = 0;
server.headersTimeout = 60 * 1000;
server.keepAliveTimeout = 65 * 1000;

// WebSocket ou autre Â« Upgrade Â» : relais brut de la connexion.
server.on('upgrade', (req, socket, head) => {
  const upstream = net.connect(web.cible_port, web.cible_hote, () => {
    const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
    for (let i = 0; i < req.rawHeaders.length; i += 2) lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
    lines.push(`X-Forwarded-For: ${clientIp(req)}`);
    upstream.write(lines.join('\r\n') + '\r\n\r\n');
    if (head && head.length) upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

server.on('clientError', (err, socket) => {
  if (socket.writable) socket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
});

function listenError(what, port) {
  return (err) => {
    if (err.code === 'EADDRINUSE') {
      log(`${what} : le port ${port} est dÃ©jÃ  utilisÃ© (MYCOGEN V1, une autre passerelle, ou MYCOGEN `
        + `lui-mÃªme s'il Ã©coute encore sur ${port} â€” voir LISEZMOI.md).`);
    } else if (err.code === 'EACCES') {
      log(`${what} : accÃ¨s refusÃ© au port ${port} (choisir un port au-dessus de 1024).`);
    } else {
      log(`${what} : erreur d'Ã©coute sur le port ${port} : ${err.message}`);
    }
    process.exit(1);
  };
}

server.on('error', listenError('web', web.ecoute_port));
server.listen(web.ecoute_port, web.ecoute_hote, () => {
  log(`web : http://${web.ecoute_hote}:${web.ecoute_port}  ->  http://${web.cible_hote}:${web.cible_port}`);
  const ips = Object.values(os.networkInterfaces()).flat()
    .filter((i) => i && i.family === 'IPv4' && !i.internal).map((i) => i.address);
  if (ips.length) log(`web : adresse(s) Ã  donner aux postes : ${ips.map((ip) => `http://${ip}:${web.ecoute_port}`).join('  ')}`);
});

// ---------------------------------------------------------------------------- automates (TCP brut)
for (const relay of config.automates) {
  if (relay.actif === false) continue;
  const name = relay.nom || `automate ${relay.ecoute_port}`;
  const targetHost = relay.cible_hote || '127.0.0.1';
  const tcp = net.createServer((client) => {
    const peer = `${clientIp(client)}:${client.remotePort}`;
    log(`${name} : connexion de ${peer}`);
    const upstream = net.connect(relay.cible_port, targetHost);
    upstream.setKeepAlive(true, 60 * 1000);
    client.setKeepAlive(true, 60 * 1000);
    client.pipe(upstream);
    upstream.pipe(client);
    const close = (why) => () => {
      log(`${name} : fin de connexion ${peer} (${why})`);
      client.destroy();
      upstream.destroy();
    };
    upstream.on('error', (err) => close(`MYCOGEN : ${err.code || err.message}`)());
    client.on('error', (err) => close(`automate : ${err.code || err.message}`)());
    upstream.on('close', () => client.destroy());
    client.on('close', () => upstream.destroy());
  });
  tcp.on('error', listenError(name, relay.ecoute_port));
  tcp.listen(relay.ecoute_port, relay.ecoute_hote || '0.0.0.0', () => {
    log(`${name} : port ${relay.ecoute_port}  ->  ${targetHost}:${relay.cible_port}`);
  });
}

// ---------------------------------------------------------------------------- arrÃªt
function stop() {
  log('arrÃªt de la passerelle');
  server.close();
  process.exit(0);
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
process.on('uncaughtException', (err) => log(`erreur inattendue : ${err.stack || err}`));
