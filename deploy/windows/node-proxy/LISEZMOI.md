# MYCOGEN V2 — passerelle réseau Node.js

## Le problème

Sur le serveur, MYCOGEN V2 (Django + PostgreSQL) tourne dans **Ubuntu (WSL2)**. Le pare-feu Windows et le
pare-feu Hyper-V bloquent les connexions des autres PC vers WSL. Pour ouvrir le port, il faudrait les droits
administrateur, que nous n'avons pas.

MYCOGEN V1 (`npm start`) fonctionne parce que **`node.exe` est déjà autorisé** par le pare-feu Windows. Cette
règle a été créée la première fois que Node a été lancé, quand Windows a demandé « Autoriser l'accès ».

## La solution

On **ne réécrit pas MYCOGEN**. Un petit programme Node (`passerelle.js`, sans aucune dépendance npm) tourne
sous Windows. Il reçoit les connexions des postes et les transmet à MYCOGEN, qui reste dans Ubuntu avec
PostgreSQL :

```
PC du labo ──► http://<IP_SERVEUR>:8000 ──► node.exe (passerelle, Windows, déjà autorisé)
                                              │  connexion locale, jamais bloquée
                                              ▼
                                   MYCOGEN Django dans WSL : 127.0.0.1:8001 ──► PostgreSQL (WSL)
```

L'adresse ne change pas pour les utilisateurs : toujours `http://<IP_SERVEUR>:8000`.

## Installation sur le serveur (sans droits administrateur)

### 1. Diagnostic (2 minutes)

Copier ce dossier sur le serveur (par exemple `D:\MycogenV2-NodeJS`), puis double-cliquer sur
**`diagnostic.bat`**. Vérifier les points suivants :

- **Règles du pare-feu qui autorisent node.exe** : au moins une ligne `[OK]` avec `action=Allow`.
  - Si `ports=Any`, n'importe quel port convient : garder 8000.
  - Si la règle ne cite qu'un port (par exemple celui de V1), mettre ce port dans `config.json`
    (`web.ecoute_port`). V1 doit alors être arrêtée, ou passer sur un autre port.
  - Le `node.exe` cité dans la règle doit être celui utilisé pour V1 (le script le signale sinon).
- **Profils** : le profil de la règle (`Domain`, `Private` ou `Public`) doit correspondre au profil
  du réseau affiché juste au-dessus. C'est déjà le cas puisque V1 fonctionne.

### 2. Faire écouter MYCOGEN en local seulement (dans Ubuntu)

Dans Ubuntu, mettre à jour le code, puis ajouter deux lignes au fichier `.env` de MYCOGEN :

```bash
cd /srv/mycogen && sudo -u mycogen git pull
sudo nano /srv/mycogen/.env
```

```
MYCOGEN_HOST=127.0.0.1
MYCOGEN_PORT=8001
```

```bash
sudo systemctl restart mycogen-web
curl -I http://127.0.0.1:8001/
```

La commande `curl` doit répondre `HTTP/1.1 302`, c'est-à-dire une redirection vers la page de connexion.
`DJANGO_ALLOWED_HOSTS` et `DJANGO_CSRF_TRUSTED_ORIGINS` ne changent pas : la passerelle transmet l'adresse
`<IP_SERVEUR>:8000` telle quelle.

> Pourquoi un autre port : en mode réseau WSL « miroir », Ubuntu et Windows partagent les mêmes ports. Si
> MYCOGEN occupait encore le port 8000, la passerelle ne pourrait pas s'y installer.

### 3. Lancer la passerelle

1. Ouvrir `demarrer.bat` avec le Bloc-notes et vérifier la ligne `set DISTRO=Ubuntu-24.04`. Le nom exact de
   la distribution est donné par `wsl -l -v`.
2. Double-cliquer sur **`demarrer.bat`**. Le script réveille Ubuntu (PostgreSQL et MYCOGEN démarrent seuls),
   garde Ubuntu allumé, puis lance la passerelle. Si la passerelle s'arrête, elle redémarre seule.
3. Depuis **un autre PC** du labo, ouvrir `http://<IP_SERVEUR>:8000`.

Lancement manuel, comme pour V1 : `npm start` dans ce dossier, à condition qu'Ubuntu soit déjà démarré.

### 4. Démarrage automatique

Double-cliquer sur **`installer-demarrage-auto.bat`**. Le script crée un raccourci dans le dossier
« Démarrage » du compte Windows. MYCOGEN démarre alors à chaque **ouverture de session** de ce compte.
Pour retirer ce raccourci : `desinstaller-demarrage-auto.bat`.

> Sans droits administrateur, Windows ne peut pas lancer un programme **avant** l'ouverture d'une session.
> Il faut donc laisser la session du serveur **ouverte et verrouillée** (Windows + L), et non fermée. Après
> une coupure de courant, il faut rouvrir la session. Si un administrateur passe un jour, il pourra
> configurer une tâche planifiée « au démarrage » qui lance `demarrer.bat`.

## Automates en réseau (GeneXpert…)

Ce point ne concerne que les automates qui **se connectent au serveur** (mode « TCP serveur » dans
MYCOGEN → Automates). L'automate ne peut pas joindre WSL directement : la passerelle doit relayer son port.

1. Dans MYCOGEN → Automates, remplacer le port de l'automate, par exemple 12000, par **12100**.
2. Dans `config.json`, section `automates`, régler `"actif": true`. Garder `ecoute_port: 12000` (le port
   déjà configuré sur l'automate) et `cible_port: 12100`.
3. Redémarrer le service automates (`sudo systemctl restart mycogen-automates`), puis la passerelle.

Rien n'est à changer sur l'automate lui-même. Les automates en mode « TCP client », dossier ou port série
ne sont pas concernés.

## Fichiers

| Fichier | Rôle |
|---|---|
| `passerelle.js` | la passerelle (Node ≥ 18, aucune dépendance) |
| `config.json` | ports d'écoute et cibles (web et automates) |
| `demarrer.bat` | démarre Ubuntu puis la passerelle, et la relance si elle s'arrête |
| `installer-demarrage-auto.bat` / `desinstaller-demarrage-auto.bat` | ajoute ou retire le lancement à l'ouverture de session |
| `diagnostic.bat` / `diagnostic.ps1` | vérifications du pare-feu et du réseau, en lecture seule |
| `test-passerelle.js` | auto-test (`npm test`) |
| `logs/passerelle.log` | journal (connexions des automates, erreurs) |

## En cas de problème

| Symptôme | Cause probable |
|---|---|
| Page « MYCOGEN est momentanément indisponible » | Ubuntu ou MYCOGEN pas démarré : `wsl -d Ubuntu-24.04`, puis `systemctl status mycogen-web` et `curl -I http://127.0.0.1:8001/` |
| `le port 8000 est déjà utilisé` dans la fenêtre | MYCOGEN écoute encore sur 8000 (étape 2 non faite), ou V1 utilise ce port |
| Le serveur affiche MYCOGEN mais pas les autres PC | règle node.exe absente pour ce port ou ce profil réseau : relancer `diagnostic.bat` |
| `Bad Request (400)` | adresse utilisée par le poste absente de `DJANGO_ALLOWED_HOSTS` (`.env` d'Ubuntu) |
