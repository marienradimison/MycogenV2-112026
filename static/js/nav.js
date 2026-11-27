/* Bouton « Préc. » : lien simple vers la page parente logique de la page affichée (liste d'une fiche, fiche d'un
 * formulaire de modification, module d'un sous-module, tableau de bord…), calculé côté serveur.
 * L'ancienne pile d'historique (sessionStorage) est effacée : elle pouvait ramener vers un objet supprimé. */
(function () {
  try { sessionStorage.removeItem('mycogen.nav'); } catch (e) {}
})();
