# MYCOGEN — Mise en production sur le serveur

> Guide pas à pas pour passer de l'ordinateur portable de développement au **serveur** de l'Unité des
> Mycobactéries, et pour arrêter l'ancien LIMS. Suivre les étapes dans l'ordre et cocher chaque case.
> Dans ce document, `<IP_SERVEUR>` désigne l'adresse IP fixe du serveur (à remplacer partout).

---

## Vue d'ensemble

| Quand | Étape | Durée indicative |
|---|---|---|
| **Veille (J-1)** | 1. Préparer le code et les fichiers sur le portable | 30 min |
| **J-1 ou J matin** | 2. Installer le serveur (logiciels, base vide, MYCOGEN) | 1 h 30 |
| **J — bascule** | 3. Geler l'ancien LIMS, transférer la base, réimporter le dernier export | 45 min |
| **J — bascule** | 4. Mettre en service (démarrage automatique, pare-feu, sauvegarde) | 30 min |
| **J — bascule** | 5. Vérifier (liste de contrôle) puis ouvrir aux utilisateurs | 30 min |
| **J+1 → J+7** | 6. Suivi après mise en production | — |

Pendant la bascule (étape 3), **personne ne saisit** ni dans l'ancien LIMS ni dans MYCOGEN : prévenir l'équipe
la veille et choisir un créneau (ex. 7 h – 9 h).

**Ce qui passe du portable au serveur**

| Élément | Comment | Remarque |
|---|---|---|
| Code de MYCOGEN | Git (dépôt GitHub) ou copie du dossier | sans `.venv`, `staticfiles`, `logs`, `dev.sqlite3`, `.env` |
| Base de données | sauvegarde PostgreSQL (`.dump`) → restauration | contient utilisateurs, rôles, CDT, projets, études, codes, matériels, fiches importées |
| Fichiers `media\` | copie (clé USB / réseau) | photos de profil, photos du fil « Chaud », logos |
| Dossier `documents\` | copie | dernier export de l'ancien LIMS, `correspondance_provenances.csv` |
| `.env` | **NON** : recréé sur le serveur | nouvelle clé secrète, `DEBUG=False`, IP du serveur |

---

## 1. Veille (J-1) — sur le portable

- [ ] **Tests** : tous doivent passer.
  ```bash
  .venv\Scripts\python manage.py test apps
  ```
- [ ] **Enregistrer le code dans Git** puis l'envoyer sur GitHub (le serveur le récupérera) :
  ```bash
  git add -A
  ```
  ```bash
  git commit -m "Version de mise en production"
  ```
  ```bash
  git push
  ```
  > Le fichier `.env`, les journaux et les données ne sont pas envoyés (exclus par `.gitignore`).
  > Sans accès Internet sur le serveur : copier le dossier `Mycogen` sur une clé USB **sans** `.venv`,
  > `staticfiles`, `logs`, `dev.sqlite3` ni `.env`.
- [ ] **Noter les comptes utilisateurs** existants (Administration → Utilisateurs) et les mots de passe de test
  à changer après la bascule.
- [ ] **Préparer une clé USB chiffrée** (BitLocker To Go) pour transporter la base et les fichiers : ils
  contiennent des **données de santé nominatives**.
- [ ] **Prévenir l'équipe** : créneau de bascule, nouvelle adresse `http://<IP_SERVEUR>:8000`, et l'arrêt
  définitif de l'ancien LIMS à la fin de la bascule.

---

## 2. Installer le serveur

### 2.1 Pré-requis

- [ ] Windows (10/11 Pro ou Server 2019+), compte **administrateur**.
- [ ] **Adresse IP fixe** `<IP_SERVEUR>` (à demander au service informatique), et si possible un nom DNS
  (ex. `mycogen.ipm.local`).
- [ ] **Fuseau horaire** : *(UTC+03:00) Nairobi / Antananarivo* ; heure synchronisée (Paramètres → Heure).
- [ ] **Compte Windows de service** dédié (ex. `svc-mycogen`, mot de passe fort, n'expire pas) : c'est lui qui
  fera tourner MYCOGEN et les sauvegardes. L'ajouter aux administrateurs **ou** lui donner les droits sur le
  dossier `D:\Mycogen` et « Ouvrir une session en tant que tâche ».
- [ ] **Accès Internet** pendant l'installation (logiciels, paquets Python). En production, Internet sert aux
  bibliothèques d'affichage (Bootstrap) et aux actualités scientifiques : **vérifier que le serveur y accède**
  (sinon l'affichage se dégrade — voir § 6).
- [ ] Disque : au moins **20 Go libres**, et un **second support** pour les sauvegardes (autre disque, NAS).

### 2.2 Logiciels

Installer, avec les **mêmes versions** que sur le portable (Python 3.13, PostgreSQL 18) :

- [ ] **Python 3.13** (python.org) — cocher *Add python.exe to PATH* et *Install for all users*.
- [ ] **PostgreSQL 18** (installeur EDB) — noter le mot de passe du compte `postgres` (coffre-fort / enveloppe
  scellée). Port **5432**. pgAdmin 4 est installé avec.
- [ ] **Git for Windows** (si le code vient de GitHub).
- [ ] **Microsoft Edge** (ou Google Chrome) — indispensable pour les **PDF** (comptes rendus, fiches).
  Windows Server 2019 n'a pas Edge par défaut : l'installer.

### 2.3 Base de données vide

Dans pgAdmin : *PostgreSQL 18 → Query Tool* (connecté en `postgres`), exécuter (F5) — choisir un **nouveau mot
de passe solide**, différent de celui du portable :

```sql
CREATE USER mycogen WITH PASSWORD 'mot-de-passe-solide';
CREATE DATABASE mycogen OWNER mycogen ENCODING 'UTF8';
```

- [ ] Ne **pas** lancer `migrate` ni `init_mycogen` maintenant : les tables viendront de la sauvegarde (étape 3).
- [ ] PostgreSQL n'accepte que les connexions locales : laisser `pg_hba.conf` tel quel (pas d'ouverture du port
  5432 dans le pare-feu ; l'administration se fait sur le serveur ou par bureau à distance).

### 2.4 MYCOGEN

Dans PowerShell (en administrateur) :

```bash
git clone https://github.com/marienradimison/MycogenV2-112026.git D:\Mycogen
```
```bash
cd D:\Mycogen
```
```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

Générer une **clé secrète** neuve (la copier pour le `.env`) :

```bash
.venv\Scripts\python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Créer `D:\Mycogen\.env` (copie de `.env.example`) avec :

```ini
DJANGO_SECRET_KEY=<clé générée ci-dessus>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<IP_SERVEUR>,<nom DNS éventuel>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<IP_SERVEUR>:8000

DB_NAME=mycogen
DB_USER=mycogen
DB_PASSWORD=<mot de passe choisi en 2.3>
DB_HOST=localhost
DB_PORT=5432

NEWS_AUTO_FETCH=True
# HTTPS_PROXY=http://proxy:3128      (seulement si Internet passe par un proxy)
# PDF_BROWSER=C:\chemin\vers\msedge.exe (seulement si Edge/Chrome n'est pas à l'emplacement standard)
```

> ⚠ `DJANGO_DEBUG=False` est **obligatoire** en production (sécurité, performances).
> Le fichier `.env` contient des secrets : ne jamais l'envoyer par e-mail ni le mettre dans Git.

- [ ] Créer le **fichier de mot de passe PostgreSQL** du compte de service (pour les sauvegardes automatiques) :
  ouvrir une session Windows avec `svc-mycogen`, puis créer
  `C:\Users\svc-mycogen\AppData\Roaming\postgresql\pgpass.conf` contenant une ligne :
  ```
  localhost:5432:mycogen:mycogen:<mot de passe de 2.3>
  ```
  Clic droit → Propriétés → Sécurité : accès réservé à `svc-mycogen` et aux administrateurs.

---

## 3. Jour J — bascule

### 3.1 Geler l'ancien LIMS

- [ ] Heure de gel annoncée (ex. 7 h) : **plus aucune saisie** dans l'ancien LIMS.
- [ ] Corriger d'abord dans l'ancien LIMS ce qui ne doit pas revenir : le n° **26-0000** (erreur de saisie,
  supprimé dans MYCOGEN le 11/11) sera réimporté s'il existe encore ; idem pour les n° illisibles
  (« I-669 », « I-831 », « 26. ») listés dans `import_rapport.csv`.
- [ ] **Exporter** toutes les fiches de l'ancien LIMS en JSON (comme le fichier du 11/11) ; nommer le fichier
  `GNX_CL_JJ_MM_AAAA.json` ; le copier sur le serveur dans `D:\documents\`.

### 3.2 Dernière sauvegarde du portable

- [ ] Sur le portable, **arrêter MYCOGEN** (fermer le serveur / terminer les tâches) pour que plus rien ne change.
- [ ] Sauvegarder la base :
  ```bash
  scripts\backup_postgres.bat
  ```
  → fichier `D:\Sauvegardes\Mycogen\mycogen_AAAA-MM-JJ_HHMM.dump`.
- [ ] Copier sur la clé USB chiffrée : ce `.dump`, le dossier `media\`, le dossier `documents\`
  (avec `correspondance_provenances.csv`).

### 3.3 Restaurer sur le serveur

- [ ] Copier `media\` dans `D:\Mycogen\media\` et `documents\` dans `D:\documents\`.
- [ ] Restaurer la base (PowerShell, dans `D:\Mycogen`) :
  ```bash
  & "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -h localhost -U mycogen -d mycogen --no-owner --no-privileges --single-transaction "E:\mycogen_AAAA-MM-JJ_HHMM.dump"
  ```
  (mot de passe de 2.3 demandé ; aucun message d'erreur ne doit apparaître)
- [ ] Mettre à niveau la base et les rôles (sans effet si le code est identique, mais toujours à faire) :
  ```bash
  .venv\Scripts\python manage.py migrate
  ```
  ```bash
  .venv\Scripts\python manage.py init_mycogen
  ```
  > Ne **jamais** utiliser `init_mycogen --demo` en production.

### 3.4 Réimporter le dernier export de l'ancien LIMS

Les fiches importées le 11/11 ont pu recevoir des résultats depuis dans l'ancien LIMS : on les **remplace**
par celles du dernier export (`--replace`). La commande refuse de le faire si l'une d'elles a déjà été
complétée dans MYCOGEN (lecture d'étuve, validation, saisie…) : dans ce cas, relancer **sans** `--replace`
(seules les nouvelles fiches seront ajoutées) et signaler les fiches concernées.

1. Essai (rien n'est enregistré) :
   ```bash
   .venv\Scripts\python manage.py import_legacy D:\documents\GNX_CL_JJ_MM_AAAA.json --replace --dry-run
   ```
2. Si l'essai est correct (nombres cohérents, pas d'erreur) :
   ```bash
   .venv\Scripts\python manage.py import_legacy D:\documents\GNX_CL_JJ_MM_AAAA.json --replace
   ```
3. Recalculer les statuts :
   ```bash
   .venv\Scripts\python manage.py refresh_sample_status
   ```
- [ ] Lire `D:\documents\import_rapport.csv` (fiches importées, doublons, ignorées, points à vérifier).

---

## 4. Mise en service

### 4.1 Pare-feu Windows

*Pare-feu Windows Defender → Paramètres avancés → Règles de trafic entrant → Nouvelle règle* :

- [ ] Port **TCP 8000** — Autoriser — profils **Domaine** et **Privé** uniquement — nom « MYCOGEN web ».
- [ ] Ports des automates en réseau (ex. **TCP 12000** pour le GeneXpert) — mêmes profils — « MYCOGEN automates ».
- [ ] **Ne pas** ouvrir le port 5432 (PostgreSQL).

### 4.2 Démarrage automatique (Planificateur de tâches)

Pour chaque tâche : *Créer une tâche* (pas « tâche de base »), compte **`svc-mycogen`**, cocher
*Exécuter même si l'utilisateur n'est pas connecté* et *Exécuter avec les autorisations maximales* ;
onglet Paramètres : *Si la tâche échoue, redémarrer toutes les 5 minutes* ; décocher
*Arrêter la tâche si elle s'exécute plus de 3 jours*.

| Tâche | Déclencheur | Action (Programme / Commencer dans) |
|---|---|---|
| MYCOGEN — serveur web | Au démarrage | `D:\Mycogen\scripts\start_mycogen.bat` / `D:\Mycogen` |
| MYCOGEN — automates | Au démarrage | `D:\Mycogen\scripts\start_automates.bat` / `D:\Mycogen` |
| MYCOGEN — sauvegarde | Tous les jours, 22 h | `D:\Mycogen\scripts\backup_postgres.bat` / `D:\Mycogen` |

- [ ] Clic droit sur « MYCOGEN — serveur web » → **Exécuter** ; ouvrir `D:\Mycogen\logs\serveur.log` :
  la ligne « Mycogen disponible sur http://0.0.0.0:8000 » doit apparaître, **sans** l'avertissement
  « DJANGO_DEBUG=True ».
- [ ] Lancer de même « MYCOGEN — automates ».
- [ ] Lancer « MYCOGEN — sauvegarde » une fois et vérifier qu'un fichier `.dump` apparaît dans
  `D:\Sauvegardes\Mycogen` (si la tâche ne se termine pas : le `pgpass.conf` du compte de service est absent).
- [ ] **Copie hors serveur** des sauvegardes : copier régulièrement (au moins chaque semaine) le dossier
  `D:\Sauvegardes\Mycogen` sur un autre support (NAS, disque externe rangé ailleurs). Une sauvegarde sur le même
  disque ne protège pas contre une panne du serveur.
- [ ] Vérifier que `D:\Sauvegardes\Mycogen` existe bien sur ce serveur (sinon adapter `DEST` dans
  `scripts\backup_postgres.bat`).

### 4.3 Automates

- [ ] Sur chaque PC d'automate (GeneXpert Dx, BD EpiCenter/MGIT) : remplacer l'adresse du LIS par
  **`<IP_SERVEUR>`** (même port) — voir le guide, section 11.
- [ ] Dans MYCOGEN → Automates → Configuration : vérifier les appareils et ports ; après toute modification,
  redémarrer la tâche « MYCOGEN — automates ».
- [ ] Contrôler les **premiers messages réels** (Automates → Messages reçus) : l'interprétation a été écrite
  d'après la documentation des fabricants et doit être confirmée sur de vrais résultats.

---

## 5. Vérifications avant d'ouvrir aux utilisateurs

Depuis **un autre PC** du réseau, ouvrir `http://<IP_SERVEUR>:8000` :

- [ ] Connexion avec un compte administrateur ; tableau de bord affiché avec la mise en page normale.
- [ ] **CNRM → Échantillons** : le nombre total correspond au rapport d'import ; ouvrir une fiche importée
  (patient, analyses, résultats, statut).
- [ ] **Compte rendu** d'un échantillon validé → *Télécharger le PDF* : un **fichier PDF** est téléchargé
  (si une page HTML s'affiche à la place avec un message : Edge/Chrome absent → § 2.2 ou `PDF_BROWSER`).
- [ ] **Export CSV** de la liste des échantillons : s'ouvre dans Excel **avec les accents** corrects.
- [ ] **Analyses TB → Culture LJ → En étuve** : les cultures en cours sont présentes.
- [ ] **Validation** : la liste des résultats à valider s'affiche.
- [ ] Enregistrer un **échantillon de test**, le vérifier, puis le **supprimer** (et son patient).
- [ ] Les photos de profil et du fil « Chaud » s'affichent (dossier `media\` bien copié).
- [ ] `D:\Mycogen\logs\mycogen.log` ne contient pas d'erreur.

Si tout est correct : **ouvrir l'accès** (message à l'équipe avec l'adresse) ; l'ancien LIMS passe en
**consultation seule** (ou est arrêté) — ne plus jamais y saisir.

---

## 6. Sécurité et données

- [ ] **Mots de passe** : changer ceux des comptes utilisés pendant les essais ; un compte nominatif par
  personne (pas de compte partagé) ; supprimer ou désactiver les comptes de test.
- [ ] **Administrateurs** : limiter les super-utilisateurs à 1–2 personnes ; les autres reçoivent des rôles
  (TL, SL, MB, AS, RSR, RQ/CQ, AL).
- [ ] **Portable de développement** : il contient encore la base avec des **données nominatives** et le
  fichier d'export JSON. Après la bascule réussie : arrêter définitivement MYCOGEN sur le portable (supprimer
  ses tâches planifiées), puis **supprimer** la base locale et les exports, ou les garder **chiffrés**
  (BitLocker) si une copie de secours est voulue. Faire de même pour la clé USB de transfert.
- [ ] Ne jamais exposer MYCOGEN sur Internet : intranet uniquement.
- [ ] **Bibliothèques d'affichage** : si le serveur n'a pas Internet, la mise en forme se dégrade. Demander
  l'installation locale de ces bibliothèques (≈ 1 Mo) pour ne plus dépendre d'Internet.

---

## 7. Plan de retour arrière

En cas de problème bloquant le jour J :

1. Ne pas supprimer l'ancien LIMS ni son export : il peut **reprendre le service** immédiatement (il n'a pas
   été modifié pendant la bascule).
2. Sur le serveur : corriger, puis recommencer à l'étape 3.3 (restauration) — la base peut être vidée et
   restaurée autant de fois que nécessaire avant l'ouverture.
3. Après l'ouverture : toute saisie se fait dans MYCOGEN ; en cas de panne, restaurer la **dernière
   sauvegarde** (guide, section 8) sur le serveur ou un poste de secours.

---

## 8. Après la mise en production (J+1 → J+7)

- [ ] **Chaque matin** : une sauvegarde de la veille existe dans `D:\Sauvegardes\Mycogen` ; la copie hors
  serveur est faite chaque semaine. **Tester une restauration** sur un autre poste dans le premier mois.
- [ ] **Provenances** : compléter la colonne `code_cdt` de `D:\documents\correspondance_provenances.csv`
  (propositions à côté), puis relancer l'import **sans** `--replace` pour rattacher les CDT :
  ```bash
  .venv\Scripts\python manage.py import_legacy D:\documents\GNX_CL_JJ_MM_AAAA.json
  ```
- [ ] Traiter les **points à vérifier** de `import_rapport.csv` (dates invalides, études multiples, cultures
  contaminées, QuantiFERON notés en remarque).
- [ ] **Cultures LJ de 90 jours et plus** : Lecture étuve → filtre « 90 jours et plus » → sortie négative en groupe.
- [ ] Surveiller `logs\mycogen.log`, `logs\serveur.log` et `logs\automates.log` ; noter les remarques des
  utilisateurs (menu *Signaler un problème*).
- [ ] **Mises à jour du code** : toujours sauvegarder d'abord, puis suivre le guide (section 5, « Mettre à
  jour MYCOGEN »).

---

*Document à conserver avec le guide MYCOGEN (`docs/GUIDE_MYCOGEN.md`).*
