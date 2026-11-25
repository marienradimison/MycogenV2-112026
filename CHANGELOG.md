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
