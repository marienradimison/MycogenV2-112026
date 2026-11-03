/* Bouton « Préc. » : remonte le parcours de l'utilisateur dans l'application.
 * Chaque page visitée est empilée ; revenir sur une page déjà présente dans la pile
 * (par Préc. ou après un enregistrement) coupe la pile à cet endroit. Ainsi :
 * liste → fiche → compte rendu → Préc. → fiche → Préc. → liste (et non le compte rendu). */
(function () {
  var KEY = 'mycogen.nav';
  var stack = [];
  try { stack = JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) { stack = []; }
  var here = location.pathname + location.search;
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(stack)); } catch (e) {} }

  if (!/[?&]format=pdf/.test(here) && !/^\/connexion\//.test(location.pathname)) {
    var i = stack.lastIndexOf(here);
    if (i >= 0) stack = stack.slice(0, i + 1);
    else stack.push(here);
    if (stack.length > 60) stack = stack.slice(-60);
    save();
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.back-btn');
    if (!btn) return;
    e.preventDefault();
    var target = stack.length > 1 ? stack[stack.length - 2] : (btn.dataset.fallback || '/');
    location.href = target;
  });
})();
