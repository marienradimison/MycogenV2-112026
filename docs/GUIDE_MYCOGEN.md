# MYCOGEN — Guide de référence et suivi du projet

**LIMS de l'Unité des Mycobactéries — Centre National de Référence des Mycobactéries (CNRM)**
**Institut Pasteur de Madagascar**

| Élément | Détail |
|---|---|
| Version du document | 1.0 — 15/10/2026 |
| Application | MYCOGEN (LIMS web, intranet) |
| Dépôt du projet | `D:\Perso\LIMS\Mycogen` |
| Base de données | PostgreSQL 18 — base `mycogen` |

---

## Sommaire

1. [Présentation](#1-présentation)
2. [Technologies utilisées](#2-technologies-utilisées)
3. [Organisation du code](#3-organisation-du-code)
4. [Installation sur le serveur](#4-installation-sur-le-serveur)
5. [Démarrage, arrêt et mise à jour](#5-démarrage-arrêt-et-mise-à-jour)
6. [Accès depuis les PC utilisateurs](#6-accès-depuis-les-pc-utilisateurs)
7. [Gestion de la base de données (pgAdmin, Navicat)](#7-gestion-de-la-base-de-données)
8. [Sauvegarde et restauration](#8-sauvegarde-et-restauration)
9. [Utilisateurs, rôles et droits](#9-utilisateurs-rôles-et-droits)
10. [Guide d'utilisation par module](#10-guide-dutilisation-par-module)
11. [Connexion des automates](#11-connexion-des-automates)
12. [Commandes d'administration](#12-commandes-dadministration)
13. [Dépannage](#13-dépannage)
14. [Suivi du projet](#14-suivi-du-projet)

---

## 1. Présentation

MYCOGEN est le système de gestion de laboratoire (LIMS) de l'Unité des Mycobactéries. Il couvre :

- **la réception** des échantillons (CNRM) : enregistrement patient + prélèvement, numérotation `26-0001`, fiche
  échantillon, compte rendu et fiche paillasse en PDF, validation des résultats ;
- **le diagnostic de la tuberculose** : GeneXpert MTB/RIF Ultra et XDR, NPOC Pluslife, microscopie (Ziehl-Neelsen,
  fluorescence), culture LJ et MGIT, antibiogramme, QuantiFERON-TB Gold Plus ;
- **la recherche** : projets, études et cas, séquençage (WGS, tNGS — ONT, Illumina), PCR (RISK6, Sweeney3), LPA Hain ;
- **la biobanque** : congélateurs, boîtes, positions, aliquots, mouvements ;
- **la bioinformatique** : pipelines et analyses génomiques ;
- **la qualité** : plan de masse, salles, matériels (maintenance, étalonnage), accès aux salles, surveillance ;
- **la vie de l'unité** : tableau de bord, fil « Chaud Chaud Chaud!!! », actualités scientifiques, organigramme.

MYCOGEN est une **application web** utilisée en **intranet** : elle est installée sur un seul serveur, et les
utilisateurs y accèdent depuis leur navigateur, sans rien installer sur leur PC.

---

## 2. Technologies utilisées

| Domaine | Technologie | Rôle |
|---|---|---|
| Langage | **Python 3.13** | Tout le code serveur de MYCOGEN |
| Framework web | **Django 5.2 LTS** (support jusqu'en avril 2028) | Pages, formulaires, sécurité, droits, administration |
| Base de données | **PostgreSQL 18** (pilote psycopg 3) | Stockage de toutes les données |
| Interface | HTML, CSS, JavaScript, **Bootstrap 5.3**, Bootstrap Icons | Mise en page, composants, icônes |
| Composants JS | Tom Select (listes avec recherche), Chart.js (graphiques) | Formulaires, tableau de bord, températures |
| Police | **Creato Display** (fichiers inclus dans le projet) | Typographie de toute l'application |
| Serveur de production | **waitress** + **whitenoise** | Service web sous Windows, fichiers statiques |
| PDF | **Microsoft Edge** (mode sans fenêtre) | Comptes rendus, fiches paillasse, fiches de lecture |
| Automates | Protocole **ASTM** (E1381/E1394), pyserial | GeneXpert, BD MGIT |
| Import Excel | openpyxl | Liste des CDT |
| Images | Pillow | Photos de profil, photos du fil d'information |
| Configuration | python-dotenv (fichier `.env`) | Mots de passe, adresse du serveur, options |

Les dépendances Python sont listées dans `requirements.txt`.

---

## 3. Organisation du code

```
Mycogen/
├── manage.py                 point d'entrée des commandes Django
├── requirements.txt          dépendances Python
├── .env                      configuration locale (NON partagée : mots de passe)
├── .env.example              modèle de .env
├── mycogen/                  configuration du projet (settings.py, urls.py)
├── apps/
│   ├── core/                 CNRM : patients, échantillons, enregistrement, validation, documents PDF,
│   │                         structures/CDT, salles et plan de masse, bibliothèque de codes, paramètres,
│   │                         journal d'audit, tableau de bord, moteur de listes/fiches (crud.py)
│   ├── diagnostic/           GeneXpert, NPOC, microscopie, culture (LJ : étuve, lectures, températures),
│   │                         antibiogramme, QuantiFERON
│   ├── research/             projets, études, cas, séquençage, PCR, LPA
│   ├── biobank/              congélateurs, boîtes, aliquots, mouvements
│   ├── bioinfo/              pipelines, analyses génomiques
│   ├── instruments/          connexion des automates (ASTM), messages, suivi en temps réel
│   ├── quality/              matériels, accès aux salles, surveillance
│   ├── feed/                 « Chaud Chaud Chaud!!! », actualités scientifiques
│   └── stock/                articles, lots, mouvements de stock
├── templates/                pages HTML (une par écran) et documents imprimables
├── static/                   CSS, JavaScript, polices, logos, images (organigramme, motif aloalo)
├── media/                    fichiers téléversés (photos, rapports…) — à sauvegarder
├── scripts/                  démarrage du serveur, des automates, sauvegarde PostgreSQL
├── logs/                     journaux de fonctionnement
└── docs/                     ce guide
```

Chaque module (`apps/...`) contient : `models.py` (tables de la base), `views.py` (écrans), `urls.py` (adresses),
`migrations/` (évolutions de la base) et `tests.py` (tests automatiques).

---

## 4. Installation sur le serveur

> Les étapes ci-dessous valent pour le **nouveau serveur** (Windows) comme pour une réinstallation.
> Prévoir un compte administrateur Windows.

### 4.1 Logiciels à installer

1. **Python 3.13** (python.org) — cocher « Add python.exe to PATH ».
2. **PostgreSQL 18** (postgresql.org, installeur EDB) — noter le mot de passe de l'utilisateur `postgres`.
   pgAdmin 4 est installé avec.
3. **Microsoft Edge** (déjà présent sous Windows) — utilisé pour produire les PDF.

### 4.2 Créer la base de données (pgAdmin)

Dans pgAdmin : clic droit sur **PostgreSQL 18 → Query Tool**, puis exécuter (F5) :

```sql
CREATE USER mycogen WITH PASSWORD 'mot-de-passe-solide';
CREATE DATABASE mycogen OWNER mycogen ENCODING 'UTF8';
```

### 4.3 Installer MYCOGEN

1. Copier le dossier du projet sur le serveur, par exemple `D:\Mycogen`.
2. Ouvrir PowerShell dans ce dossier et créer l'environnement Python :

```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

3. Copier `.env.example` en `.env` et le compléter :

| Variable | Valeur | Explication |
|---|---|---|
| `DJANGO_SECRET_KEY` | longue chaîne aléatoire | Clé de sécurité, à garder secrète |
| `DJANGO_DEBUG` | `False` en production | `True` seulement pour le développement |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,<IP du serveur>` | Adresses autorisées (actuellement 192.168.67.89) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `mycogen`, `mycogen`, mot de passe | Connexion PostgreSQL |
| `DB_HOST`, `DB_PORT` | `localhost`, `5432` | Serveur PostgreSQL |
| `NEWS_AUTO_FETCH` | `True` / `False` | Actualités scientifiques automatiques |
| `HTTPS_PROXY` | ex. `http://proxy:3128` | Seulement si l'accès Internet passe par un proxy |
| `PDF_BROWSER` | chemin d'Edge/Chrome | Seulement si Edge n'est pas à l'emplacement standard |

4. Créer les tables, les rôles et le premier administrateur :

```bash
.venv\Scripts\python manage.py migrate
```
```bash
.venv\Scripts\python manage.py init_mycogen
```
```bash
.venv\Scripts\python manage.py createsuperuser
```

5. Importer la liste des CDT :

```bash
.venv\Scripts\python manage.py import_cdt "Liste 250 CDT 23_08_2022.xlsx" "Nouveaux CDT  2026.xlsx"
```

### 4.4 Ouvrir le réseau

- **Pare-feu Windows** → Règles de trafic entrant → Nouvelle règle → Port TCP **8000** → Autoriser →
  profils **Domaine et Privé uniquement**.
- Si des automates sont connectés en réseau : ouvrir aussi leurs ports (ex. 12000 pour GeneXpert).

### 4.5 Démarrage automatique (Planificateur de tâches)

Créer trois tâches (Déclencheur : « Au démarrage » ; option « Exécuter même si l'utilisateur n'est pas connecté ») :

| Tâche | Programme | Rôle |
|---|---|---|
| MYCOGEN — serveur web | `scripts\start_mycogen.bat` | Application web sur le port 8000 |
| MYCOGEN — automates | `scripts\start_automates.bat` | Réception des résultats GeneXpert / MGIT |
| MYCOGEN — sauvegarde | `scripts\backup_postgres.bat` (quotidienne, ex. 22 h) | Sauvegarde de la base |

---

## 5. Démarrage, arrêt et mise à jour

### Démarrer / arrêter
- **Démarrage** : automatique au démarrage du serveur (tâches ci-dessus), ou double-clic sur
  `scripts\start_mycogen.bat`.
- **Arrêt** : Planificateur de tâches → clic droit sur la tâche → Terminer.
- **Mode développement** (poste de développement uniquement) : `.venv\Scripts\python manage.py runserver`.

### Mettre à jour MYCOGEN (nouvelle version du code)
1. Faire une **sauvegarde** de la base (section 8).
2. Arrêter les tâches MYCOGEN.
3. Remplacer le code (sans écraser `.env`, `media\` ni `logs\`).
4. Exécuter :
```bash
.venv\Scripts\python -m pip install -r requirements.txt
```
```bash
.venv\Scripts\python manage.py migrate
```
```bash
.venv\Scripts\python manage.py init_mycogen
```
5. Redémarrer les tâches. Les navigateurs rechargent automatiquement les nouveaux styles.

### Changer de serveur
Installer le nouveau serveur (section 4), **restaurer** la dernière sauvegarde (section 8), copier `media\`,
adapter l'adresse IP dans `.env`, dans la configuration LIS des automates et dans le pare-feu.

---

## 6. Accès depuis les PC utilisateurs

- **Rien à installer** sur les PC : un navigateur récent suffit (**Chrome** ou **Edge**).
- Adresse : **http://192.168.67.89:8000** (actuellement) — à remplacer par l'adresse du nouveau serveur.
- Conseil : créer un **raccourci** sur le bureau ou un **favori**.
- Chaque utilisateur se connecte avec son identifiant ; « Mot de passe oublié ? » envoie une demande à
  l'administrateur (pas d'e-mail en intranet).
- **Connexion Internet** : les bibliothèques d'affichage (Bootstrap, icônes) sont chargées depuis Internet.
  Sans Internet, la mise en forme se dégrade → voir « À faire » (section 14).
- Après une mise à jour, si l'affichage paraît incorrect : **Ctrl + F5**.

---

## 7. Gestion de la base de données

> **Règle d'or : on ne modifie pas les données directement dans la base pendant l'utilisation normale.**
> Toutes les saisies passent par MYCOGEN, qui contrôle les règles (validation, calculs, traçabilité,
> journal d'audit). L'accès direct sert à la consultation, aux extractions, aux sauvegardes et aux dépannages.

### 7.1 Paramètres de connexion

| Paramètre | Valeur |
|---|---|
| Hôte | `localhost` (sur le serveur) ou IP du serveur |
| Port | `5432` |
| Base | `mycogen` |
| Utilisateur | `mycogen` (ou `postgres`) |

Pour se connecter **depuis un autre PC**, PostgreSQL doit l'autoriser (fichiers `postgresql.conf` :
`listen_addresses` et `pg_hba.conf`). Par sécurité, préférer travailler **sur le serveur**.

### 7.2 pgAdmin 4
- **Se connecter** : Servers → PostgreSQL 18 → Databases → `mycogen` → Schemas → public → Tables.
- **Consulter une table** : clic droit → View/Edit Data → First 100 Rows.
- **Requête SQL** : clic droit sur `mycogen` → Query Tool.
- **Sauvegarde** : clic droit sur `mycogen` → **Backup…** → Format *Custom* → fichier `.dump`.
- **Restauration** : clic droit sur une base vide → **Restore…** → choisir le `.dump`.

### 7.3 Navicat (Navicat for PostgreSQL / Premium)
- **Connexion** → PostgreSQL → Host `localhost`, Port `5432`, Initial Database `mycogen`,
  User `mycogen`, mot de passe.
- Tables visibles dans `mycogen → public`.
- Sauvegarde : outil **Backup** de Navicat ou **Dump SQL File** (clic droit sur la base).
- Export Excel/CSV d'une table ou d'une requête : clic droit → Export Wizard.

### 7.4 Principales tables
Les tables sont nommées `module_modèle` :

| Table | Contenu |
|---|---|
| `core_patient` | Patients |
| `core_sample` | Échantillons (n° `26-0001`, analyses demandées, statut) |
| `core_facility` | Structures de provenance / CDT |
| `core_room` | Salles du plan de masse |
| `core_analysiscode` | Bibliothèque de codes : analyses (GNX-RIF, Cult-LJ…), résultats (GXMOY, RIFND, RARE, 100…), antibiotiques, R/S, rôles |
| `core_activitylog` | Journal d'audit (qui a fait quoi, quand) |
| `diagnostic_genexperttest`, `diagnostic_npoctest`, `diagnostic_microscopy`, `diagnostic_culture`, `diagnostic_dst`, `diagnostic_quantiferon` | Résultats de diagnostic |
| `diagnostic_culturetube`, `diagnostic_incubatorreading`, `diagnostic_readingentry`, `diagnostic_temperaturelog` | Culture LJ : tubes, lectures d'étuve, températures |
| `research_*` | Projets, études, cas, séquençage, PCR, LPA |
| `biobank_*` | Biobanque |
| `quality_equipment`, `quality_roomaccess` | Matériels et accès aux salles |
| `instruments_instrument`, `instruments_instrumentmessage` | Automates et messages reçus |
| `auth_user`, `auth_group` | Comptes utilisateurs et rôles |

**Ne jamais** modifier ou supprimer les tables `django_migrations` ni les colonnes `id`.

---

## 8. Sauvegarde et restauration

### Sauvegarde automatique
`scripts\backup_postgres.bat` crée chaque jour `D:\Sauvegardes\Mycogen\mycogen_AAAA-MM-JJ_HHMM.dump`
et conserve **30 jours**. Le mot de passe est lu dans `%APPDATA%\postgresql\pgpass.conf` :

```
localhost:5432:mycogen:mycogen:mot-de-passe
```

### À sauvegarder aussi
- le dossier **`media\`** (photos, rapports joints) ;
- le fichier **`.env`** (à conserver en lieu sûr) ;
- une **copie hors du serveur** (disque externe, serveur de fichiers IPM), au moins chaque semaine.

### Restauration
```bash
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -h localhost -U mycogen -d mycogen --clean fichier.dump
```
Ou dans pgAdmin : clic droit sur la base → Restore…

> Tester une restauration sur une base de test au moins une fois par trimestre.

---

## 9. Utilisateurs, rôles et droits

Les comptes se gèrent dans **Administration → Utilisateurs & paramètres → Utilisateurs** (réservé aux administrateurs).

- Le **poste** (ex. « Technicienne de laboratoire ») se renseigne dans le bloc *Poste et profil* de la fiche
  utilisateur. **C'est un titre : il n'accorde aucun droit.**
- Les **rôles** donnent les permissions. Un utilisateur peut avoir **plusieurs rôles** : ses droits s'additionnent.
- Les codes des rôles sont enregistrés dans la **Bibliothèque de codes** (catégorie « Rôle »).

| Code | Rôle | Permissions principales |
|---|---|---|
| **TL** | Technicien(ne) de Laboratoire | Enregistrer patients/échantillons ; saisir tous les résultats (diagnostic, recherche) ; biobanque ; messages d'automates ; consulter matériels et accès ; consulter le stock et **enregistrer des sorties** |
| **SL** | Surveillant(e) de Laboratoire | Diagnostic et biobanque complets (y compris suppression) ; automates ; **gestion complète du stock** ; consultation recherche, qualité, journal d'audit |
| **MB** | Médecin Biologiste | Tout le CNRM, le diagnostic, la recherche, la biobanque, les automates ; **validation des résultats** ; journal d'audit ; consultation qualité et stock |
| **AS** | Agent de Saisie | Enregistrer et modifier patients et échantillons ; consulter structures, salles, projets / études / cas |
| **RSR** | Researcher | Recherche et bioinformatique complètes ; biobanque ; échantillons ; consultation du diagnostic et du stock |
| **RQ/CQ** | Responsable Qualité / Correspondant Qualité | Matériels, accès aux salles, surveillance ; modification des salles ; consultation des automates, congélateurs, températures, stock, journal d'audit |
| **AL** | Agent de Laboratoire | Consulter échantillons, cultures, salles, matériels ; **saisir les températures d'étuve** ; consulter le stock et **enregistrer des sorties** |

Un **administrateur** (superutilisateur) a tous les droits. Les demandes de réinitialisation de mot de passe et les
signalements de bugs arrivent dans **Administration → Support** (cloche rouge dans le bandeau).

---
## 10. Guide d'utilisation par module

### Éléments communs
- **Bandeau** : recherche globale, bascule thème clair/sombre, menu du profil (paramètres, mot de passe,
  signalement d'un problème, déconnexion).
- **Barre latérale** : le CNRM y affiche ses sous-modules ; chaque autre module (Analyses TB, Recherche, Biobanque,
  Automates, Stock, Qualité, Administration) a une seule entrée qui ouvre sa page d'accueil (tuiles des sous-modules).
  Dans un module, une **barre de sous-navigation** en haut de page permet de passer d'un sous-module à l'autre.
  La barre latérale se replie avec le bouton à droite du logo (choix mémorisé).
- **Listes** : recherche, filtres, export CSV (encodé en UTF-8 : les accents s'affichent correctement dans Excel) ; **double-clic** sur une ligne pour ouvrir la fiche.
- **Bouton « ‹ Préc. »** : remonte le parcours dans l'application.
- **Validation** : tout résultat saisi (ou reçu d'un automate) est « Saisi » ; il devient « Validé » après validation
  par un biologiste, avec un commentaire facultatif. Seuls les résultats validés figurent sur le compte rendu.
- **Paramètres du compte** : photo de profil, thème, mot de passe, signalement de problème.

### Module 1 — Tableau de bord
Indicateurs (échantillons du jour, Xpert MTB+, microscopies BAAR+, cultures en cours), courbe des
échantillons reçus sur 30 jours, résultats en attente de validation, **organigramme** de l'unité (clic pour agrandir),
**Chaud Chaud Chaud!!!** (publications urgentes avec photo, réactions, commentaires, sonnerie à chaque nouvelle
publication) et **actualités scientifiques** (3 articles par semaine sur la tuberculose : PubMed, OMS, presse
reconnue).

- **Chaud Chaud Chaud!!!** : trois types de publication — *Message*, *Sondage* (2 à 10 choix, vote anonyme et
  modifiable, résultats en %, clôture par l'auteur) et *Challenge* (jeu de mots, devinette : réponse cachée, indice
  facultatif ; accents et majuscules ignorés ; gagnants dans l'ordre ; l'auteur dévoile la réponse).
### Module 2 — CNRM
- **Échantillons** : liste de tous les échantillons ; la fiche affiche patient, échantillon, analyses demandées et
  résultats (en attente / en cours / validé), avec les boutons **Compte rendu** et **Fiche paillasse**
  (aperçu imprimable ou PDF) et **Modifier** (rouvre le formulaire d'enregistrement).
- **Statut des échantillons (automatique)** : *Reçu* (saisie faite) → *En cours d'analyse* (au moins une analyse
  demandée sans résultat ; une culture en étuve compte comme sans résultat) → *En attente de validation* (résultats
  complets, au moins un non validé) → *Terminé* (tout validé) ; *Rejeté* si non conforme. Recalcul à chaque saisie,
  modification ou validation ; commande `refresh_sample_status` pour tout recalculer.
- **Enregistrer** : formulaire en 2 étapes.
  1. *Général* : fiche patient complète (l'âge se calcule ; un ID patient connu reprend sa fiche) et informations
     échantillon (n° proposé automatiquement au format `26-0001`, type, précision, dates, provenance, prescripteur).
  2. *Examens* : projet / étude / cas, analyses demandées (codes de la bibliothèque), conformité. Une fois
     l'étude choisie, le champ *Cas* suit la configuration de l'étude : liste des cas spécifiques, tous les cas du
     projet, zone de saisie libre, ou aucun cas.
- **Validation** : un onglet par test — GeneXpert MTB/RIF Ultra, GeneXpert XDR, NPOC (Pluslife), Microscopie,
  Culture LJ, Culture MGIT, Antibiogramme, QuantiFERON-TB (+ PCR, LPA… s'il y en a) ; filtres statut (à valider /
  validés / tous), dates, projet, recherche ; validation en lot avec commentaire par résultat ; bouton **Exporter (CSV)**
  — table globale ou du test sélectionné, avec les filtres appliqués (UTF-8, séparateur « ; », s'ouvre dans Excel). Les résultats sont présentés en **codes de la bibliothèque** (survol = signification,
  légende en bas du tableau) : GeneXpert `GXNEG` à `GXTEL` + `RIFND`/`RIFDE`/`RIFIN` ; XDR `INH R`, `FLQ S`… ;
  fluorescence et culture LJ `RARE`, `100`, `200`, `300` ; antibiogramme `INH R`, `STR S`…
  Présentation : positif = bordure rouge, négatif = bordure verte, en cours = bordure bleue, contaminé /
  indéterminé = rouge sans bordure précédé de « ! », non fait / non applicable = grisé (pas de TTP affiché). Un code désactivé dans la
  bibliothèque est remplacé par le libellé en clair.
- **Structures / CDT** : 322 CDT du PNLT + CBC ; bouton **Plan de masse**.
- **Plan de masse** : deux niveaux (étage de l'unité ; RDC — laboratoire P3, accessible en cliquant sur l'escalier
  entre les salles 7 et 8). Clic sur une salle : responsable, personnes autorisées, matériels, alertes.

### Module 3 — Analyses TB
- **3a GeneXpert** : onglet *Suivi en temps réel* (appareils connectés, tests en cours avec barre de progression,
  derniers résultats, actualisation toutes les 15 s) et onglet *Tests réalisés* (RIF Ultra et XDR).
- **3b NPOC (Pluslife)** : même organisation que GeneXpert.
- **3c Microscopie** : saisie Ziehl-Neelsen / fluorescence avec cotation.
- **3d Culture LJ** :
  - *En étuve* : cultures et tubes en étuve, âge, étape, LPA à faire, retraitements ;
  - *Ensemencement* : ensemencement en lot des échantillons (nombre de tubes : 1 ou 2) et des retraitements.
    La date d'ensemencement est la date de mise en étuve ; pour une culture contaminée ré-ensemencée, c'est aussi
    la date de retraitement (affichée sur la fiche de la culture d'origine) ;
  - *Lecture étuve* (hebdomadaire) : observation tube par tube, décision automatique —
    > 90 j sans pousse → négative ; pousse + test SD positif → CMTB ; pousse + SD négatif → non CMTB / LPA ;
    2 tubes contaminés → à retraiter ; 1 tube contaminé → tube jeté, l'autre reste ;
  - *Fiches de lecture* : historique ; **une fiche par lecture** (et non par échantillon) regroupant toutes les
    cultures lues, avec les totaux par décision. Depuis *Lecture étuve*, bouton **Fiche de lecture vierge** : liste
    des cultures en étuve à cocher devant l'étuve ;
  - *Températures* : relevés de l'étuve (36–38 °C), action corrective obligatoire hors plage ;
  - *Résultats LJ*.
  - Le délai de positivité est calculé automatiquement (date du résultat − ensemencement).
- **Culture MGIT** : liste des cultures (circuit dédié à construire).
- **Antibiogramme (DST)** : saisi **par groupe** — première ligne (SIRE + PZA : streptomycine, isoniazide, rifampicine,
  éthambutol, pyrazinamide) ou seconde ligne ; pour chaque antibiotique R, S, I (indéterminé), NF (non fait) ou NA
  (non applicable).
- **QuantiFERON-TB** (interprétation automatique selon l'algorithme Qiagen).

### Recherche (dont la bioinformatique)
Projets (avis éthique, membres), études et cas, runs de séquençage et librairies, PCR RISK6 / Sweeney3
(score Sweeney3 calculé), LPA Hain ; **bioinformatique** : pipelines versionnés, analyses génomiques (lignée, profil
de résistance, mutations, couverture, cluster).

**Configurer les études et cas** (Recherche → Études & cas, ou Administration) : pour chaque étude, choisir
*Saisie du cas* — « Cas du projet (tous) », « Cas spécifiques à l'étude » (cocher les cas autorisés, du même
projet), « Cas à saisir (texte libre) » (avec un libellé, ex. « N° d'inclusion ») ou « Pas de cas ».

### Biobanque
Congélateurs, boîtes (plan visuel des positions), aliquots (souche, ADN, plasma, DBS…), filiation, mouvements.

### Stock (géré par le rôle SL)
- **Tableau de bord** : articles sous le seuil d'alerte, lots périmés ou proches de la péremption (60 jours), sortie rapide.
- **Articles** (réactifs, kits, cartouches, milieux, consommables, EPI) avec seuil d'alerte, conservation et salle de stockage.
- **Lots** : n° de lot, péremption, quantité reçue ; le stock restant se calcule à partir des mouvements.
- **Mouvements** : sortie / consommation, retour, ajustement d'inventaire, perte ou péremption. Les lots sont proposés du plus proche de la péremption au plus lointain (FEFO).

### Automates
Suivi en temps réel de tous les appareils, messages reçus (et messages à traiter), configuration des appareils.

### Qualité
- **Surveillance** : matériels en panne, maintenances et étalonnages en retard ou à venir (30 jours), accès expirés,
  températures d'étuve hors plage.
- **Matériels** : registre par salle (prochaine maintenance / étalonnage calculés depuis la périodicité).
- **Accès aux salles** : personnes autorisées (validité, formation biosécurité).

### Administration
Bibliothèque de codes (catégories : Analyse, Résultat, Antibiotique, Résistance aux antibiotiques, Rôle),
salles du plan de masse, journal d'activité (audit), support, utilisateurs.

---

## 11. Connexion des automates

1. **Automates → Configuration** : déclarer chaque appareil (type, salle, connexion, port).
2. Côté appareil (logiciel GeneXpert Dx : *Configure → System → LIS Communications*) : protocole ASTM, adresse IP du
   serveur MYCOGEN et port ; activer *Host Query* pour le suivi des tests en cours.
3. Démarrer le service des automates (`scripts\start_automates.bat`) ; le relancer après toute modification.
4. Les résultats arrivent « Saisi » et doivent être validés. Un ID d'échantillon inconnu va dans
   **Messages reçus → À traiter**, où on peut l'associer au bon échantillon.

> L'interprétation GeneXpert / MGIT doit être **vérifiée sur les premiers messages réels** avant usage en routine.
> Le format d'export **Pluslife** reste à configurer (fichier exemple nécessaire).

---

## 12. Commandes d'administration

À lancer dans le dossier du projet : `.venv\Scripts\python manage.py <commande>`

| Commande | Rôle |
|---|---|
| `migrate` | Met à jour la structure de la base (après chaque mise à jour du code) |
| `init_mycogen` | Crée / met à jour les rôles et leurs droits (`--demo` : données fictives) |
| `createsuperuser` | Crée un compte administrateur |
| `import_cdt <fichiers.xlsx>` | Importe / met à jour la liste des CDT (sans doublon) |
| `fetch_news [--force]` | Récupère les actualités scientifiques de la semaine |
| `serve [--port 8000]` | Lance le serveur web de production |
| `instruments_listen` | Lance la réception des messages des automates |
| `test apps` | Lance les tests automatiques (50 tests) |

---

## 13. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| Page « Bad Request (400) » | Adresse non autorisée | Ajouter l'IP / le nom du serveur dans `DJANGO_ALLOWED_HOSTS` (`.env`) puis redémarrer |
| Mise en page cassée, plan noir | Ancienne version en cache ou pas d'Internet | **Ctrl + F5** ; vérifier l'accès Internet (bibliothèques) |
| « Port 8000 déjà utilisé » | MYCOGEN déjà lancé | Utiliser l'instance existante ou arrêter la tâche |
| Erreur de connexion à la base | PostgreSQL arrêté ou mot de passe | Services Windows → `postgresql-x64-18` démarré ; vérifier `.env` |
| « PDF indisponible » | Edge introuvable | Renseigner `PDF_BROWSER` dans `.env` ; en attendant : Imprimer → Enregistrer en PDF |
| Pas d'actualités scientifiques | Pas d'accès Internet / proxy | Renseigner `HTTPS_PROXY` dans `.env` ; `fetch_news --force` |
| Un automate n'envoie rien | Service des automates arrêté, port fermé | Lancer `start_automates.bat`, vérifier pare-feu et configuration LIS |
| Journaux | — | Dossier `logs\` (`mycogen.log`, `serveur.log`, `automates.log`) |

---

## 14. Suivi du projet

### 14.1 État d'avancement des modules

| Module | État | Remarques |
|---|---|---|
| Bandeau, thème, navigation, paramètres | ✅ Terminé | Barre latérale rétractable, Préc., thème sombre |
| 1 — Tableau de bord | ✅ Terminé | Organigramme, Chaud Chaud Chaud!!!, actualités |
| 2 — CNRM (échantillons, enregistrement, validation, structures) | ✅ Terminé | Compte rendu et fiche paillasse PDF |
| Plan de masse (étage + RDC P3) | ✅ Terminé | 37 salles ; usages et noms à compléter |
| Qualité (matériels, accès, surveillance) | ✅ Terminé | Registres à alimenter |
| Navigation par modules (« Analyses TB », bioinformatique dans Recherche) | ✅ Terminé | Sous-navigation en haut de page |
| 3a — GeneXpert | ✅ Terminé | Suivi temps réel opérationnel dès connexion des appareils |
| 3b — NPOC (Pluslife) | ✅ Terminé (interface) | Format d'export Pluslife à recevoir |
| 3c — Microscopie | ✅ Validé sans modification | |
| 3d — Culture LJ | ✅ Terminé | Étuves à déclarer dans Qualité → Matériels |
| 3d — Culture MGIT | ⏳ À faire | Circuit MGIT à décrire |
| 3e — Antibiogramme (DST) | ⏳ À revoir | |
| 3f — QuantiFERON-TB | ⏳ À revoir | |
| Recherche (dont bioinformatique), Biobanque | ⏳ À revoir | Version initiale en place |
| Stock (articles, lots, mouvements) | ✅ Terminé | Géré par le rôle SL ; articles à saisir |
| Rôles TL / SL / MB / AS / RSR / RQ-CQ / AL | ✅ Terminé | Poste = titre seulement ; rôles cumulables |
| Stock (articles, lots, mouvements) | ✅ Terminé | Géré par le rôle SL ; articles à saisir |
| Rôles TL / SL / MB / AS / RSR / RQ-CQ / AL | ✅ Terminé | Poste = titre seulement ; rôles cumulables |
| Connexion des automates | 🟡 Prêt, à tester | Vérifier sur messages réels GeneXpert / MGIT |
| Portail externe des laboratoires régionaux | 🔜 Futur | API sécurisée à prévoir |

### 14.2 À faire avant le lancement officiel
- [ ] Supprimer les **données de démonstration** (24 patients fictifs, 4 structures fictives).
- [ ] Créer les comptes utilisateurs et leur attribuer leur rôle.
- [ ] Renseigner les salles (noms, usages, responsables), les matériels et les accès.
- [ ] Déclarer les étuves et les automates.
- [ ] Installer sur le **nouveau serveur** et mettre `DJANGO_DEBUG=False`.
- [ ] Installer les bibliothèques d'affichage **en local** (fonctionnement sans Internet).
- [ ] Mettre en place et **tester** la sauvegarde + une copie hors serveur.
- [ ] Former les utilisateurs (ce guide, section 10).

### 14.3 Journal des évolutions

| Date | Évolution |
|---|---|
| 11/10/2026 | Création de MYCOGEN : modules de base, PostgreSQL, rôles, tests |
| 11/10/2026 | Import des 322 CDT, NPOC, connexion des automates (ASTM), déploiement intranet |
| 12/10/2026 | Nouvelle identité visuelle (Creato Display, motif aloalo, thème sombre), module Paramètres, support |
| 12/10/2026 | Tableau de bord : Chaud Chaud Chaud!!!, actualités scientifiques, organigramme |
| 13/10/2026 | Module CNRM : enregistrement en 2 étapes, fiche paillasse et compte rendu PDF, validation |
| 13/10/2026 | Bibliothèque de codes, bouton Préc., délai de positivité calculé, structure CBC |
| 14/10/2026 | Plan de masse interactif, module Qualité (matériels, accès, surveillance) |
| 14/10/2026 | Barre latérale rétractable, tableaux compacts ; GeneXpert et NPOC : suivi en temps réel |
| 15/10/2026 | Culture LJ (étuve, lecture hebdomadaire, fiches, températures) ; plan RDC — laboratoire P3 ; fusion 12b/12c |
| 15/10/2026 | Guide MYCOGEN ; nouveaux rôles (TL, SL, MB, AS, RSR, RQ/CQ, AL) ; poste dans la fiche utilisateur ; module Stock |
| 16/10/2026 | Barre latérale par modules, sous-navigation, « Analyses TB », bioinformatique intégrée à la Recherche |
| 18/10/2026 | Culture LJ : date d'ensemencement = mise en étuve = date de retraitement, nombre de tubes (1 ou 2), fiche de lecture par lecture + fiche vierge ; études et cas configurables ; corrections (date de naissance à la modification, menu Culture LJ/MGIT) |
| 20/10/2026 | Codes de résultat (GeneXpert, RIF, BAAR/colonies, antibiotiques, R/S) dans la bibliothèque et le module Validation ; niveau GeneXpert « très élevé » ; exports CSV en UTF-8 corrigés |
| 20/10/2026 | Validation : onglets séparés (GeneXpert Ultra / XDR, culture LJ / MGIT), NPOC et antibiogramme, filtre de statut, export CSV global ou par test |
| 24/10/2026 | Statut automatique des échantillons ; antibiogramme par groupe (1re / 2e ligne, R-S-I-NF-NA) ; présentation uniforme des résultats en Validation ; sondages et challenges dans Chaud Chaud Chaud!!! |

---

*Document à mettre à jour à chaque évolution de MYCOGEN.*
