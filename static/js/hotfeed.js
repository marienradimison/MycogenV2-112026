/* « Chaud Chaud Chaud!!! » : publication, réactions, commentaires, détection des nouveautés + sonnerie. */
(function () {
  const box = document.getElementById('hot-feed');
  if (!box) return;
  const listUrl = box.dataset.url;          // fragment HTML (avec ?page=…)
  const stateUrl = box.dataset.stateUrl;    // dernière publication
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  const KEY = 'mycogen.hot.lastSeen';
  const openComments = new Set();

  // ---- Sonnerie (Web Audio, pas de fichier son) ----
  let audio = null;
  function unlock() { if (!audio) { try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
                      if (audio && audio.state === 'suspended') audio.resume(); }
  document.addEventListener('click', unlock, {once: false, passive: true});
  function ring() {
    if (!audio || audio.state !== 'running') return;
    [[880, 0], [1175, 0.16], [1568, 0.32]].forEach(([f, t]) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, audio.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.25, audio.currentTime + t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + t + 0.35);
      o.connect(g).connect(audio.destination);
      o.start(audio.currentTime + t); o.stop(audio.currentTime + t + 0.4);
    });
  }

  // ---- Rendu ----
  async function reload() {
    box.querySelectorAll('details[open]').forEach(d => openComments.add(d.dataset.post));
    const html = await (await fetch(listUrl, {headers: {'X-Requested-With': 'fetch'}})).text();
    box.innerHTML = html;
    box.querySelectorAll('details.hot-comments').forEach(d => {
      if (openComments.has(d.dataset.post)) d.open = true;
      d.addEventListener('toggle', () => d.open ? openComments.add(d.dataset.post) : openComments.delete(d.dataset.post));
    });
  }

  async function post(url, data) {
    const body = data instanceof FormData ? data : new URLSearchParams(data || {});
    const r = await fetch(url, {method: 'POST', body, headers: {'X-CSRFToken': csrf}});
    let json = {};
    try { json = await r.json(); } catch (e) {}
    return {ok: r.ok, ...json};
  }

  // Réactions, suppressions
  box.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.confirm && !confirm(btn.dataset.confirm)) return;
    const data = btn.dataset.kind ? {kind: btn.dataset.kind} : btn.dataset.option ? {option: btn.dataset.option} : {};
    await post(btn.dataset.action, data);
    reload();
  });
  // Challenges : proposer une réponse
  box.addEventListener('submit', async (e) => {
    const form = e.target.closest('form.hot-answer-form');
    if (!form) return;
    e.preventDefault();
    const res = await post(form.dataset.action, new FormData(form));
    if (res.correct) { reload(); return; }
    const fb = form.parentElement.querySelector('.answer-feedback');
    fb.innerHTML = res.error ? `<span class="text-danger">${res.error}</span>` : '<span class="text-danger">Raté, essayez encore !</span>';
    form.querySelector('input').select();
  });
  // Commentaires
  box.addEventListener('submit', async (e) => {
    const form = e.target.closest('form.hot-comment-form');
    if (!form) return;
    e.preventDefault();
    openComments.add(form.closest('details').dataset.post);
    await post(form.dataset.action, new FormData(form));
    reload();
  });

  // Nouvelle publication
  const compose = document.getElementById('hot-compose');
  if (compose) {
    const fileInput = compose.querySelector('input[type=file]');
    const fileLabel = compose.querySelector('.file-name');
    fileInput.addEventListener('change', () => { fileLabel.textContent = fileInput.files[0] ? fileInput.files[0].name : ''; });
    // Type de publication : message, sondage, challenge
    const kindInput = compose.querySelector('[name=kind]'), textarea = compose.querySelector('textarea');
    const placeholders = JSON.parse(textarea.dataset.placeholders || '{}');
    function setKind(kind) {
      kindInput.value = kind;
      compose.querySelectorAll('.hot-kinds button').forEach(b => b.classList.toggle('active', b.dataset.kind === kind));
      compose.querySelectorAll('.compose-extra').forEach(x => { x.hidden = x.dataset.for !== kind; });
      compose.querySelector('[name=answer]').required = kind === 'CHALLENGE';
      if (placeholders[kind]) textarea.placeholder = placeholders[kind];
    }
    compose.querySelectorAll('.hot-kinds button').forEach(b => b.addEventListener('click', () => setKind(b.dataset.kind)));
    compose.querySelector('.add-option').addEventListener('click', () => {
      const box = compose.querySelector('.poll-inputs'), n = box.children.length;
      if (n >= 10) return;
      const inp = box.children[0].cloneNode();
      inp.value = ''; inp.placeholder = 'Choix ' + (n + 1);
      box.appendChild(inp); inp.focus();
    });
    compose.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = compose.querySelector('button[type=submit]');
      btn.disabled = true;
      const res = await post(compose.action, new FormData(compose));
      btn.disabled = false;
      const err = compose.querySelector('.compose-error');
      if (!res.ok) { err.textContent = res.error || 'Publication impossible.'; return; }
      err.textContent = '';
      compose.reset(); fileLabel.textContent = '';
      compose.querySelectorAll('.poll-inputs input:nth-child(n+3)').forEach(i => i.remove());
      setKind('MESSAGE');
      if (res.id) localStorage.setItem(KEY, res.id);
      reload();
    });
  }

  // ---- Détection des nouvelles publications (toutes les 20 s) ----
  async function poll(first) {
    try {
      const s = await (await fetch(stateUrl)).json();
      const seen = parseInt(localStorage.getItem(KEY) || '0', 10);
      if (s.latest > seen) {
        localStorage.setItem(KEY, s.latest);
        if (!first || seen) {
          if (!first) await reload();
          if (!s.mine && seen) {
            ring();
            box.closest('.card').classList.add('hot-flash');
            setTimeout(() => box.closest('.card').classList.remove('hot-flash'), 2500);
          }
        }
      }
    } catch (e) { /* hors connexion : on réessaie au prochain tour */ }
  }
  reload().then(() => poll(true));
  setInterval(poll, 20000);
})();
