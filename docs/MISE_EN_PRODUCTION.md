# MYCOGEN — Mise en production sur le serveur

> Guide pas à pas pour passer de l'ordinateur portable de développement au **serveur** de l'Unité des
> Mycobactéries, et pour arrêter l'ancien LIMS. Suivre les étapes dans l'ordre et cocher chaque case.
> `<IP_SERVEUR>` désigne l'adresse IP fixe du serveur (à remplacer partout).

---

## 0. Le serveur et ce que cela implique

| Sur le serveur | Conséquence pour MYCOGEN |
|---|---|
| Windows 11 + **WSL2 Ubuntu 24.04** | MYCOGEN tourne **dans Ubuntu** (services `systemd`). Trois réglages Windows sont indispensables : réseau WSL en mode **miroir** (sinon les PC du réseau ne voient pas MYCOGEN), **maintien de WSL au démarrage** (sinon MYCOGEN s'arrête quand personne n'est connecté), **pare-feu**. |
| **Python 3.12.3** | Compatible (MYCOGEN a été testé avec Python 3.12 et Django 5.2.19). MYCOGEN utilise son **propre environnement** (`.venv`) : le Django installé sur le système n'est pas utilisé et ne doit pas être modifié. |
| **PostgreSQL serveur 17.11**, client 18.6 | Compatible. Mais la base du portable est en **PostgreSQL 18** : une sauvegarde 18 ne se restaure pas toujours dans un serveur 17. La sauvegarde de transfert est donc faite **sans statistiques** (`--no-statistics`), et une **répétition** du transfert est faite avant le jour J (§ 3). Solution de repli prévue (§ 3.4). |
| pgAdmin 4 | Sert à créer la base et à la consulter. |
| PDF (comptes rendus, fiches) | Nécessite **Google Chrome dans Ubuntu** (+ polices) — à installer (§ 2.4). |
| Automates | GeneXpert en réseau : sans difficulté (mode miroir). **MGIT par câble série/USB** : WSL ne voit pas les ports COM de Windows → outil `usbipd-win` ou liaison réseau via EpiCenter (§ 4.4). |

> **PostgreSQL 17 est installé dans Ubuntu (WSL)**, comme MYCOGEN : tout tourne dans Ubuntu.
> pgAdmin (sous Windows) s'y connecte avec l'hôte `localhost`, port `5432`, grâce au réseau en mode miroir.

**Ce qui passe du portable au serveur**

| Élément | Comment | Remarque |
|---|---|---|
| Code | Git (dépôt GitHub `MycogenV2-112026`) | à jour |
| Base de données | sauvegarde PostgreSQL → restauration | utilisateurs, rôles, CDT, projets, études, codes, matériels, fiches importées |
| `media\` | copie | photos de profil, photos du fil « Chaud », logos |
| `documents\` | copie | dernier export de l'ancien LIMS, `correspondance_provenances.csv` |
| `.env` | **NON** : recréé sur le serveur | nouvelle clé secrète, `DEBUG=False`, IP du serveur |

Données de santé nominatives : transport sur **clé USB chiffrée** (BitLocker To Go) ou dossier partagé
réservé aux administrateurs ; effacer les copies intermédiaires après usage.

---

## 1. Calendrier

| Quand | Étape |
|---|---|
| **Avant J** | § 2 : installer le serveur (Windows + Ubuntu) ; § 3 : **répétition** du transfert avec la base actuelle ; vérifications § 5 |
| **J — bascule** (créneau sans saisie, ex. 7 h – 9 h) | § 3 avec les données définitives ; § 4 : services ; § 5 : vérifications ; ouverture |
| **J+1 → J+7** | § 8 : suivi |

---

## 2. Installer le serveur

### 2.1 Côté Windows (PowerShell **administrateur**)

- [ ] Version : `winver` → Windows 11 **22H2 ou plus récent** (nécessaire au réseau WSL en mode miroir).
- [ ] WSL à jour :
  ```powershell
  wsl --update
  ```
  ```powershell
  wsl -l -v
  ```
  Noter le **nom exact de la distribution** (ex. `Ubuntu-24.04`) et **le compte Windows** sous lequel elle est
  installée : WSL est propre à chaque compte Windows ; tout ce qui suit (fichier `.wslconfig`, tâche de
  maintien) doit se faire avec **ce compte**.
- [ ] **IP fixe** `<IP_SERVEUR>` (service informatique) ; fuseau horaire *(UTC+03:00) Antananarivo*.
- [ ] **Réseau WSL en mode miroir** : copier `deploy\wsl\wslconfig.txt` du dépôt dans
  `C:\Users\<compte>\.wslconfig` (nom exact : `.wslconfig`), puis :
  ```powershell
  wsl --shutdown
  ```
- [ ] **Pare-feu Windows** (port web 8000 et port GeneXpert 12000, réseaux domaine/privé uniquement) :
  ```powershell
  New-NetFirewallRule -DisplayName "MYCOGEN web" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain,Private
  ```
  ```powershell
  New-NetFirewallRule -DisplayName "MYCOGEN automates" -Direction Inbound -Protocol TCP -LocalPort 12000 -Action Allow -Profile Domain,Private
  ```
- [ ] **Pare-feu Hyper-V** (filtre aussi le trafic vers WSL en mode miroir) :
  ```powershell
  New-NetFirewallHyperVRule -Name "MYCOGEN-web" -DisplayName "MYCOGEN web" -Direction Inbound -VMCreatorId "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" -Protocol TCP -LocalPorts 8000
  ```
  ```powershell
  New-NetFirewallHyperVRule -Name "MYCOGEN-automates" -DisplayName "MYCOGEN automates" -Direction Inbound -VMCreatorId "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" -Protocol TCP -LocalPorts 12000
  ```
- [ ] **Ne pas** ouvrir le port 5432 (PostgreSQL).
- [ ] Dossier de sauvegarde côté Windows : `D:\Sauvegardes\Mycogen` (visible dans Ubuntu sous
  `/mnt/d/Sauvegardes/Mycogen`). S'il n'y a pas de disque D:, adapter `BACKUP_DIR` (§ 4.1).

### 2.2 Maintenir WSL démarré (Planificateur de tâches Windows)

Sans cette tâche, Ubuntu — donc MYCOGEN — ne démarre qu'à l'ouverture d'une session et s'arrête ensuite.

*Planificateur de tâches → Créer une tâche* :
- Général : nom « MYCOGEN — démarrage WSL » ; compte = **le compte Windows propriétaire de la distribution** ;
  cocher *Exécuter même si l'utilisateur n'est pas connecté* et *Exécuter avec les autorisations maximales*.
- Déclencheur : *Au démarrage*.
- Action : programme `C:\Windows\System32\wsl.exe`, arguments `-d Ubuntu-24.04 --exec /bin/sleep infinity`
  (remplacer `Ubuntu-24.04` par le nom relevé en 2.1).
- Paramètres : décocher *Arrêter la tâche si elle s'exécute plus de…* ; *Si la tâche échoue, redémarrer toutes
  les 5 minutes*.

### 2.3 Côté Ubuntu — système

Ouvrir Ubuntu (menu Démarrer → Ubuntu), puis :

- [ ] systemd actif (doit afficher `running` ou `degraded`) :
  ```bash
  systemctl is-system-running
  ```
  Sinon : copier `deploy/wsl/wsl.conf` dans `/etc/wsl.conf` puis `wsl --shutdown` côté Windows.
- [ ] Fuseau horaire :
  ```bash
  sudo timedatectl set-timezone Indian/Antananarivo
  ```
- [ ] Paquets (environnement Python, Git, polices des documents) :
  ```bash
  sudo apt update && sudo apt install -y python3-venv python3-dev git fonts-liberation fonts-crosextra-carlito fonts-dejavu-core
  ```
- [ ] Compte de service `mycogen` (fait tourner MYCOGEN) et dossier de l'application :
  ```bash
  sudo adduser --disabled-password --gecos "MYCOGEN" mycogen
  ```
  ```bash
  sudo mkdir -p /srv/mycogen && sudo chown mycogen:mycogen /srv/mycogen
  ```

### 2.4 Google Chrome (production des PDF)

```bash
wget -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
```
```bash
sudo apt install -y /tmp/chrome.deb
```

### 2.5 Base de données vide (mot de passe **nouveau et solide**)

- [ ] PostgreSQL 17 démarre avec Ubuntu (doit afficher `enabled` puis `active`) :
  ```bash
  systemctl is-enabled postgresql && systemctl is-active postgresql
  ```
  Sinon : `sudo systemctl enable --now postgresql`.
- [ ] Créer l'utilisateur et la base :
  ```bash
  sudo -u postgres psql
  ```

```sql
CREATE USER mycogen WITH PASSWORD 'mot-de-passe-solide';
CREATE DATABASE mycogen OWNER mycogen ENCODING 'UTF8';
```

Ne **pas** lancer `migrate` maintenant : les tables viendront de la sauvegarde (§ 3).

### 2.6 MYCOGEN

```bash
sudo -iu mycogen
```
(les commandes suivantes s'exécutent en tant que `mycogen`)
```bash
git clone https://github.com/marienradimison/MycogenV2-112026.git /srv/mycogen && cd /srv/mycogen
```
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
```bash
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Créer `/srv/mycogen/.env` (`nano .env`), avec la clé affichée ci-dessus :

```ini
DJANGO_SECRET_KEY=<clé générée>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<IP_SERVEUR>,<nom DNS éventuel>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<IP_SERVEUR>:8000

DB_NAME=mycogen
DB_USER=mycogen
DB_PASSWORD=<mot de passe de 2.5>
DB_HOST=localhost
DB_PORT=5432

NEWS_AUTO_FETCH=True
# HTTPS_PROXY=http://proxy:3128    (seulement si Internet passe par un proxy)
```
```bash
chmod 600 .env
```

Fichier de mot de passe PostgreSQL pour les sauvegardes automatiques :
```bash
echo "localhost:5432:mycogen:mycogen:<mot de passe de 2.5>" > ~/.pgpass && chmod 600 ~/.pgpass
```

Vérifications :
```bash
.venv/bin/python manage.py test apps
```
(tous les tests doivent passer ; ils utilisent une base temporaire, sans toucher aux données)
```bash
.venv/bin/python manage.py shell -c "from apps.core.pdf import html_to_pdf; print(len(html_to_pdf('<h1>Test</h1>')), 'octets : PDF OK')"
```
```bash
exit
```

---

## 3. Transfert de la base (répétition avant J, puis définitif le jour J)

### 3.1 Jour J uniquement : geler l'ancien LIMS

- [ ] Heure de gel annoncée : **plus aucune saisie** dans l'ancien LIMS.
- [ ] Corriger d'abord dans l'ancien LIMS ce qui ne doit pas revenir : le n° **26-0000** (erreur, supprimé dans
  MYCOGEN le 11/11) et les n° illisibles (« I-669 », « I-831 », « 26. ») listés dans `import_rapport.csv`.
- [ ] **Exporter** toutes les fiches en JSON (`GNX_CL_JJ_MM_AAAA.json`).

### 3.2 Sur le portable : arrêter et sauvegarder

- [ ] Arrêter MYCOGEN sur le portable (fermer le serveur, terminer ses tâches planifiées).
- [ ] Sauvegarde **compatible PostgreSQL 17** (PowerShell, dans `D:\Perso\LIMS\Mycogen`) :
  ```powershell
  & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h localhost -U mycogen -w --no-statistics -F c -f "D:\Sauvegardes\Mycogen\transfert_mycogen.dump" mycogen
  ```
- [ ] Copier vers le serveur, dans `D:\transfert\` : `transfert_mycogen.dump`, le dossier `media\`, le dossier
  `documents\` (avec l'export JSON et `correspondance_provenances.csv`). Côté Ubuntu ce dossier est
  `/mnt/d/transfert/`.

### 3.3 Sur le serveur : restaurer

En tant que `mycogen` (`sudo -iu mycogen`, puis `cd /srv/mycogen`) :

- [ ] **Répétition ou nouvelle tentative uniquement** — repartir d'une base vide (avec un compte administrateur
  Ubuntu : `sudo -u postgres psql`, et MYCOGEN arrêté : `sudo systemctl stop mycogen-web mycogen-automates`) :
  ```sql
  DROP DATABASE mycogen;
  CREATE DATABASE mycogen OWNER mycogen ENCODING 'UTF8';
  ```
- [ ] Restaurer :
  ```bash
  pg_restore -h localhost -U mycogen -d mycogen --no-owner --no-privileges --single-transaction /mnt/d/transfert/transfert_mycogen.dump
  ```
  Aucun message d'erreur ne doit apparaître. En cas d'erreur (incompatibilité 18 → 17) : § 3.4.
- [ ] Mettre à niveau et copier les fichiers :
  ```bash
  .venv/bin/python manage.py migrate
  ```
  ```bash
  .venv/bin/python manage.py init_mycogen
  ```
  ```bash
  cp -r /mnt/d/transfert/media/. /srv/mycogen/media/
  ```
  > Ne **jamais** utiliser `init_mycogen --demo` en production.

### 3.4 Solution de repli si la restauration échoue

Transfert par les données de Django (indépendant de la version de PostgreSQL) — testé le 13/11 avec la base
actuelle : copie identique à l'original (échantillons, patients, CDT, codes, utilisateurs, statuts) :

1. Sur le portable (PowerShell, dans `D:\Perso\LIMS\Mycogen`) — la première ligne impose l'UTF-8 (sinon
   l'export échoue sur certains caractères) :
   ```powershell
   $env:PYTHONUTF8 = "1"
   ```
   ```powershell
   .venv\Scripts\python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry -o "D:\Sauvegardes\Mycogen\transfert_mycogen.json"
   ```
   et copier ce fichier dans `D:\transfert\` du serveur.
2. Sur le serveur, repartir d'une base vide (§ 3.3, premier point), puis :
   ```bash
   .venv/bin/python manage.py migrate
   ```
   ```bash
   .venv/bin/python manage.py flush --no-input
   ```
   (vide les quelques données créées par `migrate`, qui sinon entreraient en conflit avec le chargement)
   ```bash
   .venv/bin/python manage.py loaddata /mnt/d/transfert/transfert_mycogen.json
   ```
   ```bash
   .venv/bin/python manage.py init_mycogen && .venv/bin/python manage.py refresh_sample_status
   ```
3. Copier `media` comme au § 3.3.

### 3.5 Jour J uniquement : réimporter le dernier export de l'ancien LIMS

Les fiches importées le 11/11 ont pu recevoir des résultats depuis dans l'ancien LIMS : on les **remplace** par
celles du dernier export. La commande refuse si l'une d'elles a déjà été complétée dans MYCOGEN : relancer alors
**sans** `--replace` (seules les nouvelles fiches sont ajoutées) et signaler les fiches citées.

```bash
.venv/bin/python manage.py import_legacy /mnt/d/transfert/documents/GNX_CL_JJ_MM_AAAA.json --replace --dry-run
```
Si l'essai est correct :
```bash
.venv/bin/python manage.py import_legacy /mnt/d/transfert/documents/GNX_CL_JJ_MM_AAAA.json --replace
```
```bash
.venv/bin/python manage.py refresh_sample_status
```
- [ ] Lire `/mnt/d/transfert/documents/import_rapport.csv`.

---

## 4. Mise en service (Ubuntu, avec un compte administrateur — pas `mycogen`)

### 4.1 Services

```bash
sudo cp /srv/mycogen/deploy/wsl/mycogen-*.service /srv/mycogen/deploy/wsl/mycogen-backup.timer /etc/systemd/system/
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now mycogen-web mycogen-automates mycogen-backup.timer
```
```bash
systemctl status mycogen-web --no-pager
```
- [ ] `active (running)` ; `tail /srv/mycogen/logs/serveur.log` affiche « Mycogen disponible sur
  http://0.0.0.0:8000 », **sans** l'avertissement « DJANGO_DEBUG=True ».
- [ ] Tester la sauvegarde tout de suite :
  ```bash
  sudo mkdir -p /mnt/d/Sauvegardes/Mycogen && sudo systemctl start mycogen-backup && ls -l /mnt/d/Sauvegardes/Mycogen
  ```
  Un fichier `mycogen_….dump` doit apparaître. Autre emplacement : ajouter `Environment=BACKUP_DIR=/chemin`
  dans `/etc/systemd/system/mycogen-backup.service`, puis `sudo systemctl daemon-reload`.

### 4.2 Commandes utiles

| Besoin | Commande |
|---|---|
| Redémarrer MYCOGEN | `sudo systemctl restart mycogen-web` |
| Redémarrer les automates (après modif. de configuration) | `sudo systemctl restart mycogen-automates` |
| État | `systemctl status mycogen-web mycogen-automates mycogen-backup.timer --no-pager` |
| Journaux | `tail -f /srv/mycogen/logs/serveur.log` — `logs/mycogen.log` — `logs/automates.log` |
| Fichiers Ubuntu depuis l'explorateur Windows | `\\wsl$\Ubuntu-24.04\srv\mycogen` |

### 4.3 Mise à jour du code (plus tard)

Sauvegarde d'abord (`sudo systemctl start mycogen-backup`), puis en tant que `mycogen` :
```bash
cd /srv/mycogen && git pull && .venv/bin/pip install -r requirements.txt && .venv/bin/python manage.py migrate && .venv/bin/python manage.py init_mycogen
```
puis `sudo systemctl restart mycogen-web mycogen-automates`.

### 4.4 Automates

- [ ] **GeneXpert Dx** : adresse LIS = `<IP_SERVEUR>`, même port (12000) — fonctionne grâce au mode miroir.
- [ ] **BD MGIT / EpiCenter** : de préférence une **liaison réseau** (TCP) via EpiCenter. Si c'est un câble
  série/USB branché sur le serveur, l'installer avec **usbipd-win** (Windows) et le rattacher à Ubuntu
  (`usbipd bind` puis `usbipd attach --wsl --auto-attach`) ; dans MYCOGEN, le port devient `/dev/ttyUSB0`
  (au lieu de `COM3`). À tester avec le technicien BD.
- [ ] **Pluslife** : dossier d'export Windows accessible sous `/mnt/c/...` ou `/mnt/d/...` (à indiquer dans
  Automates → Configuration).
- [ ] Contrôler les **premiers messages réels** (Automates → Messages reçus) : l'interprétation a été écrite
  d'après la documentation des fabricants.

---

## 5. Vérifications avant d'ouvrir aux utilisateurs

Depuis **un autre PC** du réseau, `http://<IP_SERVEUR>:8000` :

- [ ] Connexion administrateur ; tableau de bord avec une mise en page normale.
- [ ] **CNRM → Échantillons** : total conforme au rapport d'import ; une fiche importée s'ouvre correctement.
- [ ] **Compte rendu** d'un échantillon validé → *Télécharger le PDF* : un **fichier PDF** est téléchargé.
- [ ] **Export CSV** des échantillons : s'ouvre dans Excel **avec les accents**.
- [ ] **Culture LJ → En étuve** et **Validation** : les listes s'affichent.
- [ ] Échantillon de test : l'enregistrer, le vérifier, puis le **supprimer** (et son patient).
- [ ] Photos (profils, fil « Chaud ») affichées.
- [ ] **Redémarrage complet du serveur Windows, sans ouvrir de session** : après 2–3 minutes, MYCOGEN doit
  répondre depuis un autre PC (vérifie la tâche § 2.2 et les services § 4.1).
- [ ] Le lendemain matin : une sauvegarde de 22 h existe dans `D:\Sauvegardes\Mycogen`.

Si tout est correct : **ouvrir l'accès** (adresse communiquée à l'équipe) ; l'ancien LIMS passe en
**consultation seule** (ou est arrêté).

---

## 6. Sécurité et données

- [ ] `DJANGO_DEBUG=False`, clé secrète neuve, `.env` et `~/.pgpass` en droits 600.
- [ ] Changer les mots de passe des comptes utilisés pendant les essais ; un compte nominatif par personne ;
  1–2 super-utilisateurs au plus, les autres avec des rôles (TL, SL, MB, AS, RSR, RQ/CQ, AL).
- [ ] **Copie hors serveur** des sauvegardes au moins chaque semaine (NAS, disque externe rangé ailleurs) ;
  tester une restauration dans le premier mois.
- [ ] Après la bascule : arrêter définitivement MYCOGEN sur le portable, puis **supprimer** (ou chiffrer avec
  BitLocker) sa base, `D:\Perso\LIMS\documents`, `D:\transfert` et la clé USB de transfert.
- [ ] MYCOGEN reste en **intranet** uniquement. Si le serveur n'a pas Internet, la mise en forme se dégrade :
  demander l'installation locale des bibliothèques d'affichage (≈ 1 Mo).

---

## 7. Plan de retour arrière

1. Tant que MYCOGEN n'est pas ouvert, l'**ancien LIMS** peut reprendre immédiatement (il n'a pas été modifié).
2. Sur le serveur, on peut vider la base et recommencer au § 3.3 autant de fois que nécessaire.
3. Après l'ouverture : toute saisie se fait dans MYCOGEN ; en cas de panne, restaurer la dernière sauvegarde
   (`pg_restore`, § 3.3) sur le serveur ou un poste de secours.

---

## 8. Après la mise en production (J+1 → J+7)

- [ ] Chaque matin : la sauvegarde de la veille existe.
- [ ] **Provenances** : compléter la colonne `code_cdt` de `correspondance_provenances.csv`, puis relancer
  l'import **sans** `--replace` :
  ```bash
  .venv/bin/python manage.py import_legacy /mnt/d/transfert/documents/GNX_CL_JJ_MM_AAAA.json
  ```
- [ ] Traiter les points à vérifier de `import_rapport.csv`.
- [ ] Cultures LJ de 90 jours et plus : Lecture étuve → filtre « 90 jours et plus » → sortie négative en groupe.
- [ ] Surveiller les journaux et les signalements des utilisateurs (*Signaler un problème*).

---

*Document à conserver avec le guide MYCOGEN (`docs/GUIDE_MYCOGEN.md`).*
