# Mycogen — LIMS

> Guide complet (installation, base de données, utilisation, suivi) : [docs/GUIDE_MYCOGEN.md](docs/GUIDE_MYCOGEN.md) — version PDF : `docs/GUIDE_MYCOGEN.pdf` (régénérer avec `.venv\Scripts\python docs\build_guide_pdf.py`).

**Institut Pasteur de Madagascar · Mycobacteria Unit**

LIMS web (Django 5.2 LTS + PostgreSQL) pour le diagnostic de la tuberculose et les activités de recherche de l'unité.

## Modules

| Module | Contenu |
|---|---|
| **CNRM** | Enregistrement en 2 étapes (patient + prélèvement, puis analyses demandées), échantillons n° `26-0001`, fiche échantillon avec résultats, compte rendu et fiche paillasse en PDF, validation des résultats, structures / CDT |
| **Diagnostic TB** | GeneXpert MTB/RIF Ultra & MTB/XDR (INH, FQ, AMK, KAN, CAP, ETH) · NPOC Pluslife MTB · Microscopie ZN / fluorescence (cotation OMS) · Culture LJ / MGIT (TTP, identification) · Antibiogramme phénotypique (DST) · QuantiFERON-TB Gold Plus (**interprétation automatique** selon l'algorithme Qiagen) |
| **Recherche** | Projets (avis éthique, membres) · Runs de séquençage WGS / tNGS (ONT, Illumina) et librairies (barcode, profondeur, couverture, QC) · PCR signatures RISK6 / Sweeney3 (**score Sweeney3 calculé** depuis les Ct) · LPA Hain MTBDRplus / MTBDRsl / CM-AS |
| **Biobanque** | Congélateurs → boîtes → positions (**plan visuel de boîte**), aliquots (prélèvement, souche, ADN, ARN, plasma, sérum, DBS, PAXgene…), filiation (ADN ← souche), mouvements (sortie, décongélation, transfert, destruction) avec mise à jour automatique du stock |
| **Automates** | Connexion GeneXpert et BD MGIT (protocole ASTM) : import automatique des résultats, suivi en temps réel des tests en cours, file des messages à traiter. Pluslife : réception des fichiers d'export (interprétation à configurer) |
| **Bioinformatique** | Pipelines versionnés (TB-Profiler, MTBseq, Deeplex…) · Analyses : lignée, sous-lignée, profil de résistance (RR/MDR/pré-XDR/XDR), mutations, couverture, cluster, rapport joint |

Fonctions transverses : tableau de bord, recherche globale, filtres + export CSV sur chaque liste, **circuit de validation** (saisi → validé par un biologiste ; un résultat validé n'est plus modifiable par un technicien), **compte-rendu patient imprimable** (résultats validés uniquement), journal d'audit, rôles et permissions.

## Installation (Windows)

PostgreSQL 18 est déjà installé sur ce poste. Créer la base et l'utilisateur (dans `psql` ou pgAdmin, connecté en `postgres`) :

```sql
CREATE USER mycogen WITH PASSWORD 'choisir-un-mot-de-passe';
CREATE DATABASE mycogen OWNER mycogen ENCODING 'UTF8';
```

Puis :

```bash
copy .env.example .env
```

Renseigner `DB_PASSWORD` et `DJANGO_SECRET_KEY` dans `.env`, puis :

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python manage.py migrate
```

```bash
.venv\Scripts\python manage.py init_mycogen
```

```bash
.venv\Scripts\python manage.py createsuperuser
```

```bash
.venv\Scripts\python manage.py runserver
```

Ouvrir http://localhost:8000. `init_mycogen --demo` ajoute en plus 24 patients fictifs pour découvrir l'outil (à ne pas utiliser en production).

## Rôles

Créés par `init_mycogen` ; on affecte les utilisateurs aux groupes dans **Administration → Utilisateurs**.

| Rôle | Droits |
|---|---|
| Réception | Patients, échantillons |
| Technicien | Saisie de tous les résultats diagnostic/recherche, biobanque |
| Biologiste | Tout + **validation des résultats** + journal d'audit |
| Chercheur | Projets, séquençage, PCR, LPA, biobanque ; lecture du diagnostic |
| Gestionnaire biobanque | Biobanque complète |
| Bioinformaticien | Analyses et pipelines, runs/librairies |

## Architecture

```
mycogen/            configuration Django
apps/core/          patients, échantillons, moteur CRUD générique (crud.py), audit, tableau de bord
apps/diagnostic/    GeneXpert, microscopie, culture, DST, QuantiFERON
apps/research/      projets, séquençage, PCR, LPA
apps/biobank/       stockage, aliquots, mouvements
apps/bioinfo/       pipelines, analyses génomiques
apps/instruments/   automates : protocole ASTM (astm.py), interprétation (handlers.py), service d'écoute
scripts/            démarrage serveur / automates, sauvegarde PostgreSQL
templates/ static/  interface (Bootstrap 5), logos
```

Ajouter un nouveau type d'analyse = un modèle héritant de `TestResult` + une déclaration `Crud(...)` dans le `views.py` du module + une entrée dans `apps/core/menu.py`. Liste, fiche, formulaire, export, validation et compte-rendu sont générés automatiquement.

Tests : `.venv\Scripts\python manage.py test apps.core`

## Structures / CDT

La liste des CDT du PNLT s'importe (et se met à jour sans doublon) avec :

```bash
.venv\Scripts\python manage.py import_cdt "..\documents\Liste 250 CDT 23_08_2022.xlsx" "..\documents\Nouveaux CDT  2026.xlsx"
```

Les noms de régions sont harmonisés (Amoron'i Mania, Vakinankaratra, Fitovinany…) et le préfixe « SDSP » est retiré des districts.

## Automates (GeneXpert, MGIT, Pluslife)

1. **Mycogen → Automates → Configuration** : déclarer chaque automate (type, connexion, port).
2. Lancer le service d'écoute, en permanence sur le serveur : `scripts\start_automates.bat`
   (ou `python manage.py instruments_listen`). Le relancer après toute modification de configuration.
3. **Suivi en temps réel** : tests en cours par automate (requêtes hôte), derniers résultats ; page actualisée toutes les 30 s.

Règles de sécurité : chaque message reçu est conservé brut ; un résultat n'est importé que si l'ID saisi
sur l'automate correspond à un **code échantillon Mycogen** (ou à son identifiant externe) ; il arrive au statut
« Saisi » et doit être **validé par un biologiste**. Les messages non reconnus vont dans **Messages reçus → À traiter**,
où l'on peut les associer au bon échantillon.

| Automate | Réglage côté automate | Côté Mycogen |
|---|---|---|
| **GeneXpert Dx** | *Configure → System → LIS Communications* : protocole ASTM, connexion réseau, adresse IP du serveur Mycogen + port, envoi automatique des résultats ; *Host Query* activé pour le suivi des tests en cours | Connexion « TCP — le LIMS écoute », même port (ex. 12000) |
| **BD MGIT 960 / EpiCenter** | Interface LIS ASTM (souvent RS-232 → adaptateur USB-série, ou TCP via EpiCenter) — paramétrage par le technicien BD | « Port série » (COMx, 9600 bauds) ou TCP |
| **Pluslife MiniDock** | Dossier d'export des résultats | « Dossier d'export » : les fichiers sont archivés dans Mycogen ; l'interprétation automatique sera ajoutée dès réception d'un fichier d'export exemple |

⚠ L'interprétation GeneXpert/MGIT suit le format ASTM documenté par les fabricants ; elle doit être **vérifiée avec les premiers messages réels**
de vos appareils (visibles dans *Messages reçus*) avant d'être utilisée en routine.

## Mise en production intranet (Windows)

1. `.env` : `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<IP du serveur>` (actuellement `192.168.67.89`), nouvelle `DJANGO_SECRET_KEY`.
2. Pare-feu Windows : autoriser en entrée le port **8000** (Mycogen) et le(s) port(s) des automates, **profil Domaine/Privé uniquement**.
3. Planificateur de tâches → « Au démarrage du système », compte de service, « Exécuter même si l'utilisateur n'est pas connecté » :
   `scripts\start_mycogen.bat` et `scripts\start_automates.bat`.
4. Sauvegarde : tâche quotidienne `scripts\backup_postgres.bat` (mot de passe dans `%APPDATA%\postgresql\pgpass.conf` :
   `localhost:5432:mycogen:mycogen:<mot de passe>`) + copie régulière de `D:\Sauvegardes\Mycogen` et du dossier `media\` hors du serveur.
5. Les postes accèdent à **http://192.168.67.89:8000**.

Migration vers le nouveau serveur : installer Python + PostgreSQL, copier le dossier du projet, restaurer la dernière sauvegarde
(`pg_restore -d mycogen fichier.dump`), adapter l'IP dans `.env`, la configuration LIS des automates et le pare-feu.

Les fichiers téléversés (rapports) ne sont accessibles qu'aux utilisateurs connectés. Journal applicatif : `logs\`.
## Tableau de bord : Chaud Chaud Chaud!!! et actualités

- **Chaud Chaud Chaud!!!** : tout utilisateur connecté publie une information (texte, photo ≤ 5 Mo, option « Urgent »), les autres réagissent (👍 ❤️ 🔥 😮 😢) et commentent. Le tableau de bord vérifie toutes les 20 s s'il y a du nouveau et joue une sonnerie (le navigateur n'autorise le son qu'après un premier clic dans la page). Suppression : auteur ou administrateur.
- **Actualités scientifiques** : 3 articles par semaine sélectionnés automatiquement (2 articles PubMed de la semaine, revues de référence en priorité + 1 actualité OMS / ScienceDaily / presse reconnue, dont presse malgache). Mise à jour automatique à l'ouverture du tableau de bord (au plus toutes les 6 h) ou par `python manage.py fetch_news`. Le serveur doit accéder à Internet (variables `HTTPS_PROXY` si proxy) ; `NEWS_AUTO_FETCH=False` dans `.env` pour désactiver.
- **Organigramme** : image `static/img/organigramme_2026.webp` — la remplacer par la nouvelle version (même nom) lors d'un changement d'équipe.