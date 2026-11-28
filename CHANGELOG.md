# Registre des modifications — MYCOGEN LIMS

Toutes les modifications notables de l'application sont consignées ici, de la plus récente à la plus ancienne.
Catégories : **Corrigé** (bugs), **Sécurité**, **Ajouté**, **Modifié**.

---

## 2026-11-25 — Biobanque : boîtes normalisées et QR codes, inventaires, traçabilité, rapports

Migration : `biobank.0004_inventaires_tracabilite` (reprend les boîtes existantes : année de création,
étagère / rack au format E03 / R01). Après mise à jour : `migrate` puis `init_mycogen` (permission de validation
des inventaires pour les rôles SL et MB).

### Ajouté

- **Localisation en chemin** : `MYCO-2209/E03/R01/SCH-2026-01/B07` (congélateur / étagère / rack / boîte / position),
  affichée dans les listes, fiches et mouvements.
- **Aliquots** : champ « solution de conservation » ; code = n° de l'échantillon source (26-4244, puis 26-4244-2…) ;
  projet et étiquette / ID externe (identifiant externe saisi à l'enregistrement) remplis automatiquement depuis l'échantillon source ou l'aliquot parent.
- **Boîtes** : type d'aliquot, nom automatique `ABR-AAAA-NN` (numérotation par type, remise à 01 chaque année,
  n° ou nom modifiable) ; fiche avec chemin, capacité / occupées / libres, étiquette 80 × 45 mm avec QR code,
  affichage du QR code, déplacement tracé de la boîte, historique.
- **Inventaires** : sessions par congélateur, étagère, rack ou boîte ; scan des QR de boîtes et des codes
  d'aliquots ; constats (conforme, manquant, non enregistré, mal positionné, étiquette / QR non conforme) ;
  soumission et validation par un responsable, avec correction optionnelle des positions ; liste des anomalies.
- **Traçabilité** : dossier d'un aliquot, d'un échantillon ou d'une boîte (localisations successives, opérations,
  quantités, cycles de congélation, filiation, inventaires, audit), journal filtrable des opérations, audit.
- **Rapports** : effectifs (type, année, projet, espèce, statut), occupation des congélateurs et des boîtes,
  capacités disponibles, entrées / sorties sur une période, inventaires et non-conformités ; exports Excel, CSV, PDF.
  *Fichiers : `apps/biobank/models.py`, `apps/biobank/views.py`, `apps/biobank/reports.py`, `templates/biobank/`*

### Modifié

- Titre de la liste « Biobanque » → **« Aliquots & Souches »**.
- Mouvements : localisation avant / après enregistrée ; le changement d'emplacement indique la boîte et la position
  de destination et met à jour l'aliquot.
- Moteur CRUD : les boutons « Nouveau » / « Modifier » ne s'affichent plus pour une vue désactivée ; liste avec
  filtre de base (`queryset`) ; l'opérateur courant est proposé par défaut.
  *Fichiers : `apps/core/crud.py`, `apps/core/templatetags/lims.py`*

---

## 2026-11-28 — Retours terrain

Migration : `core.0028_patient_tb_history_unknown`.

### Corrigé

- **Lecture d'étuve : enregistrement impossible** (erreur 400 `TooManyFieldsSent`) quand l'étuve contient plusieurs
  centaines de cultures : limite Django relevée (`DATA_UPLOAD_MAX_NUMBER_FIELDS`) et champs vides non envoyés.
- **Identifiant externe** : plus de code automatique (PTaa-nnnnn) quand il n'est pas saisi ; commande
  `clear_auto_patient_codes` (simulation, puis `--apply`) pour effacer les codes déjà générés.
- **GNX-RIF** : seule la résistance RIF est saisie et affichée (antibiotiques XDR réservés au GNX-XDR).
- **Validation** : seules les analyses dont le résultat est saisi sont listées et validables (une culture en étuve
  n'apparaît plus) ; compteur « en attente de validation » du tableau de bord aligné.

### Modifié

- Enregistrement : antécédent TB « Inconnu » par défaut (nouveau choix ; « Autre / inconnu » devient « Autre ») ;
  case « Consentement pour la recherche » retirée.
- Culture LJ (ensemencement) : décontamination NALC-NaOH par défaut.
- Lecture d'étuve : recherche d'un échantillon (n°, patient, identifiant externe), filtres par mois et par date
  d'ensemencement ; boutons « >90 jours » et « semaine | >90 jours » ; « Ouvrir toutes les fiches » devient
  « Fermer toutes les fiches » une fois ouvertes.

---

## 2026-11-27 — Bouton « Préc. » logique ; sondages et challenges à la une

Migration : `feed.0004_highlight_post_kind`.

### Corrigé

- **Préc.** suivait l'historique réel du navigateur : après une suppression, il pouvait ramener vers l'élément
  supprimé (page d'erreur). Il ramène désormais à la **page parente logique**, calculée côté serveur : fiche → liste,
  modification → fiche, création → liste, enfant → parent (entrée → cahier, résultat QFT → plaque, résultat PCR /
  librairie → run, cas → projet, support → collection), sous-module → module (SGQ, Recherche, Biobanque),
  Surveillance → Matériels, plan de masse → Accès aux salles, « À la une » → tableau de bord. Un `?next=` interne
  reste prioritaire. *Fichiers : `static/js/nav.js`, `templates/generic/_back.html`, `apps/core/crud.py` (`parent`)*

### Ajouté

- **« À la une » interactive** : un sondage ou un challenge mis à la une s'affiche avec ses choix (vote, résultats)
  ou son champ de réponse (indice, gagnants) ; si la publication est supprimée, le contenu reste avec une mention.

---

## 2026-11-27 — Tableau de bord : « À la une »

Migration : `feed.0003_a_la_une`. Après mise à jour : `migrate` puis `init_mycogen` (permission `feed.manage_highlight`
pour SL, RQ/CQ et CDS).

### Modifié

- L'organigramme du tableau de bord est remplacé par la carte **« À la une »** (titre, texte, image agrandissable,
  lien « En savoir plus »).

### Ajouté

- Bouton étoile sur les publications de Chaud Chaud Chaud!!! : « Mettre à la une » (copie modifiable du texte et de
  la photo, conservée si la publication est supprimée) ; badge « À la une » sur la publication concernée.
- Page « À la une » : modifier le contenu à tout moment, en rédiger un nouveau, historique (remettre à la une,
  retirer, supprimer). Lien limité aux pages MYCOGEN (/…) et aux adresses http(s).
  *Fichiers : `apps/feed/models.py` (Highlight), `apps/feed/views.py`, `templates/feed/highlight_form.html`,
  `templates/core/dashboard.html`*

---

## 2026-11-27 — MycoLearn : lecteurs intégrés pour tous les formats

Migration : `research.0008_lecteurs_integres`. Serveur : installer LibreOffice (voir MISE_EN_PRODUCTION.md, § 2.4).

### Ajouté

- Lecture dans MYCOGEN, sans ouvrir d'autre application : **Word** (.docx, docx-preview), **Excel / tableur / CSV**
  (SheetJS, un onglet par feuille), **Markdown** (marked + DOMPurify : scripts retirés), **HTML** (cadre isolé,
  en-tête `Content-Security-Policy: sandbox` sans `allow-same-origin`), **texte**, **PowerPoint** et anciens formats
  Office (conversion PDF par LibreOffice, mise en cache dans `media/mycolearn/apercus/`), **liens web** dans la page ;
  bouton plein écran, zoom des images.
- Types de support « Document (Word, texte) », « Tableur (Excel, CSV) », « Page web (HTML, Markdown) », déduits du
  fichier (sauf « Tutoriel »).
- Bouton « Télécharger » à la place de « Ouvrir le fichier » (le support se lit dans la page).

*Fichiers : `apps/research/viewers.py`, `apps/research/mycolearn.py`, `templates/research/learning_detail.html`*

---

## 2026-11-27 — MycoLearn : médiathèque

Migration : `research.0007_mediatheque`. Après mise à jour : `migrate` puis `init_mycogen` (consultation des
collections pour tous les rôles).

### Ajouté

- **Accueil de la médiathèque** : à la une, « Continuer », « Ma liste », nouveautés, plus consultés, collections,
  rangées par domaine ; recherche et filtres (domaine, type, niveau, langue, mot-clé, tri).
- **Lecteur** : vidéo / audio avec reprise de lecture (position enregistrée), YouTube / Vimeo intégrés avec
  miniature, PDF, images ; favoris (« Ma liste »), « terminé », compteur de consultations, supports liés.
- **Collections / parcours** (`LearningCollection`, `CollectionItem`) avec progression personnelle et enchaînement
  automatique des supports.
- Supports : type **Audio / podcast**, langue, mots-clés, « à la une » ; suivi personnel `LearningActivity`.
- **Lecture en continu** des fichiers audio / vidéo : réponses partielles HTTP 206 (`Range`), nécessaires à
  l'avance rapide et à la reprise. *Fichier : `apps/core/views.py`*

*Fichiers : `apps/research/mycolearn.py`, `templates/research/mycolearn.html`, `learning_detail.html`,
`collection_detail.html`, `_media_card.html`*

---

## 2026-11-27 — Générateur de fiches QuantiFERON, aperçu des résultats

Migration : `diagnostic.0014_qft_runs`.

### Ajouté

- **QuantiFERON-TB → Plaques ELISA** (`QFTRun`) : DO des standards en double, courbe standard (régression ln-ln
  sur S1–S3), contrôle qualité selon la notice QFT-Plus ; saisie groupée des DO brutes des échantillons ; calcul des
  UI/mL et de l'interprétation ; recalcul des résultats non validés si un standard est corrigé.
  *Fichiers : `apps/diagnostic/qft.py`, `apps/diagnostic/qft_views.py`, `templates/diagnostic/qft_run.html`*
- **Fiche « Résultats QuantiFERON®-TB Gold Plus »** par échantillon ou pour toute la plaque (HTML / PDF), avec
  la signature du validateur. *Fichier : `templates/documents/qft_sheet.html`*
- **Aperçu commun des résultats** (`templates/generic/result_detail.html`, `apps/core/result_view.py`) : bandeau
  échantillon / date / méthode / résultat, informations générales et patient, validation biologique signée,
  métadonnées, frise de traçabilité.

### Corrigé

- En-tête d'un résultat validé sans validateur (reprise de l'ancien LIMS) : « par None » n'est plus affiché.
- SGQ → Accès aux salles : le lien « Surveillance » (propre aux matériels) a été retiré.

---

## 2026-11-26 — Autorisations par rôle (permissions.xlsx)

Migration : `core.0027_validation_view_permission`. Après mise à jour : `migrate` puis **`init_mycogen`**
(qui réapplique les droits de tous les rôles).

### Modifié

- **Rôles** redéfinis par une matrice module × rôle conforme au fichier `permissions.xlsx`
  (`MATRIX` dans `apps/core/management/commands/init_mycogen.py`) ; les droits d'un rôle sont l'union des lignes
  où il figure. L'administrateur (superutilisateur) garde tous les droits.
- **Validation** : nouvelle permission `core.view_validation` (consulter et exporter la table) distincte de
  `core.validate_results` (valider) ; sans droit de valider, la page s'affiche sans cases ni bouton et refuse les
  envois.

### Ajouté

- Rôles **CDS — Chef de Service** et **STG — Stagiaire** (bibliothèque de codes, catégorie Rôle).
- Tests de la matrice des autorisations (`apps/core/test_permissions.py`).

### Ajusté (même jour)

- **MycoLearn** : consultation pour tous ; ajout, modification et suppression des contenus réservés à SL, RSR,
  RQ/CQ et CDS.
- **Documents qualité (SOP, manuels…)** : consultables par tous les rôles (menu SGQ réduit à « DQ — Documents
  qualité » pour les rôles sans autre accès SGQ) ; rédaction et approbation restent à SL, RQ/CQ et CDS.
- **AL** : consultation et saisie des températures d'étuve, par l'entrée « Températures des étuves » du module
  Analyses TB (affichée aux rôles qui n'ont pas accès à la Culture LJ) ; les onglets de la Culture LJ
  inaccessibles sont masqués.

---

## 2026-11-19 — Signatures, SGQ réorganisé, cahiers de laboratoire et MycoLearn

Migrations : `core.0026_user_signature`, `quality.0003_quality_documents`, `research.0006_notebooks_mycolearn`.
Après mise à jour : `migrate` puis `init_mycogen` (nouvelles permissions des rôles).

### Ajouté

- **Signature des utilisateurs** : image et mention dans la fiche utilisateur (Administration), avec aperçu.
  Apposée dans le bloc du validateur du compte rendu et de la fiche paillasse dès la validation, et sur les
  documents qualité approuvés ; la page Validation montre la signature de l'utilisateur connecté.
  *Fichiers : `apps/core/models.py`, `apps/core/admin.py`, `apps/core/signature.py`, `templates/documents/_validation.html`*
- **SGQ → DQ — Documents qualité** : manuels qualité, procédures, SOP, manuels clients, formulaires, communiqués…
  Versions par référence, approbation signée (permission `quality.approve_qualitydocument`, rôles MB et RQ/CQ)
  qui met le document en vigueur et archive la version précédente.
  *Fichiers : `apps/quality/models.py`, `apps/quality/views.py`, `templates/quality/document_detail.html`*
- **Recherche → Cahiers de laboratoire** : registre des cahiers et entrées datées (contenu, pièces jointes).
- **Recherche → MycoLearn** : galerie de supports d'apprentissage par domaine (7 domaines créés par défaut),
  lecture des vidéos, images et PDF dans la page.
  *Fichiers : `apps/research/models.py`, `apps/research/views.py`, `templates/research/mycolearn.html`*

### Modifié

- Module **Qualité** renommé **SGQ**, en quatre sous-modules : Suivi performance, Matériels (dont la
  surveillance), Accès aux salles (dont les salles et le plan de masse, retirés du menu Administration),
  DQ — Documents qualité.
- Recherche : sous-modules **Analyses génomiques** et **Pipelines** retirés du menu (données et URL conservées).
- Fichiers téléversés : vidéos (MP4, WebM, Ogg, MOV) lues dans le navigateur ; PDF affichables dans les pages
  MYCOGEN (`X-Frame-Options: SAMEORIGIN` pour les fichiers seulement).
- Formulaires : le rédacteur ou le titulaire est pré-rempli avec l'utilisateur connecté.

---

## 2026-11-16 — Revue de code et correction de bugs

Revue complète du code serveur : moteur CRUD, enregistrement, validation, statut des échantillons, culture LJ,
automates, stock, fil d'actualité et comptes. Aucune migration de base de données n'est nécessaire.

### Corrigé — logique métier

- **Statut des échantillons et résultats « Annulé »** : un échantillon dont un résultat était annulé restait
  bloqué en « En attente de validation ». Les résultats annulés ne comptent plus ni dans le statut de
  l'échantillon ni dans l'état des analyses.
  *Fichiers : `apps/core/status.py`, `apps/core/analyses.py`*
- **Validation unitaire d'un résultat** : le bouton « Valider » acceptait un résultat annulé ou déjà validé
  (le nom du validateur et la date étaient alors écrasés). Seuls les résultats au statut « Saisi » peuvent
  désormais être validés ; sinon un avertissement s'affiche.
  *Fichier : `apps/core/crud.py`*
- **N° d'échantillon en double (saisies simultanées)** : si deux postes enregistraient le même n° au même
  moment, le second obtenait une erreur 500. Le formulaire signale maintenant que le n° vient d'être attribué
  et propose le prochain n° libre.
  *Fichier : `apps/core/register.py`*
- **Codes générés automatiquement (dont l'identifiant patient)** : deux enregistrements simultanés pouvaient
  recevoir le même code (le verrou existant ne portait que sur les lignes déjà présentes). Sous PostgreSQL,
  un verrou consultatif par table et par préfixe, libéré à la fin de la transaction, sérialise désormais
  l'attribution.
  *Fichier : `apps/core/models.py`*
- **Stock — ajustement négatif** : un ajustement d'inventaire négatif pouvait faire passer un lot sous zéro.
  Il est maintenant contrôlé comme une sortie.
  *Fichier : `apps/stock/models.py`*
- **Stock — modification d'un mouvement** : changer le lot d'un mouvement existant faussait le calcul du stock
  disponible. L'ancien mouvement n'est plus pris en compte s'il portait sur un autre lot.
  *Fichier : `apps/stock/models.py`*
- **Retraitement LJ** : deux envois simultanés du formulaire d'ensemencement pouvaient créer deux
  retraitements pour la même culture contaminée. La culture est désormais verrouillée pendant l'opération.
  *Fichier : `apps/diagnostic/lj.py`*

### Corrigé — erreurs 500 sur des paramètres invalides

Une valeur incorrecte dans l'adresse ou un formulaire (par exemple `?project=abc`) provoquait une erreur
serveur. Ces valeurs sont maintenant ignorées ou refusées proprement :

- filtres des listes (tous les modules gérés par le moteur CRUD) — `apps/core/crud.py` ;
- `?patient=` sur la page « Enregistrer » et `?pk=` de la recherche de patient — `apps/core/register.py` ;
- `?projet=` du module Validation — `apps/core/validation.py` ;
- `?instrument=` de la liste des messages automates — `apps/instruments/views.py` ;
- choix d'option d'un sondage — `apps/feed/views.py` ;
- échantillons, cultures et étuve envoyés à l'ensemencement et à la lecture LJ (l'étuve doit en outre être
  une étuve en service) — `apps/diagnostic/lj.py`.

### Sécurité

- **Redirections vers un site externe** : les paramètres de retour `next` (création d'un objet, validation,
  bascule du thème) acceptaient une adresse comme `//site-externe.com`. Ils sont limités au site lui-même
  (nouvelle fonction `safe_next`).
  *Fichiers : `apps/core/crud.py`, `apps/core/account.py`*
- **Fichiers téléversés** : un fichier HTML (par exemple un rapport bioinformatique) s'ouvrait dans le
  navigateur et pouvait exécuter du code dans la session de l'utilisateur. Seuls les images et les PDF
  s'affichent désormais ; tout autre fichier est téléchargé (en-tête `X-Content-Type-Options: nosniff`).
  *Fichier : `apps/core/views.py`*
- **Page Support** : les statuts envoyés pour les demandes de réinitialisation et les rapports de bug sont
  contrôlés par rapport à la liste autorisée.
  *Fichier : `apps/core/account.py`*
- **Relevés de température** : un envoi sans le droit d'ajout est refusé explicitement (accès interdit) au
  lieu d'être ignoré sans message.
  *Fichier : `apps/diagnostic/lj.py`*

### Ajouté

- Tests de non-régression `RobustnessTests` (`apps/core/tests.py`) : paramètres invalides, redirection
  externe refusée, résultat annulé, téléchargement des fichiers HTML. Suite complète : 85 tests, tous réussis
  (SQLite).

### Points connus, non modifiés

- **TTP des cultures MGIT** : le délai de positivité envoyé par l'automate est remplacé par le calcul
  « date du résultat − date d'ensemencement ». Comportement voulu (couvert par un test existant), conservé.
- Le verrou PostgreSQL d'attribution des codes n'a été vérifié que sous SQLite (où il est inactif) ; à
  contrôler sur le serveur de production.

---

## 2026-11-16 — Module SGQ (Qualité)

### Ajouté
- Statistiques et indicateurs de performance du laboratoire (module Qualité).

## 2026-11-13 — Déploiement serveur

### Ajouté
- Déploiement sur serveur Windows 11 + WSL2 (Ubuntu 24.04, PostgreSQL 17) : services systemd, sauvegardes.

## 2026-11-12 — Version de mise en production

### Ajouté
- Première version mise en production de MYCOGEN LIMS.

## 2026-11-03 — Création du projet

### Ajouté
- Commit initial.
