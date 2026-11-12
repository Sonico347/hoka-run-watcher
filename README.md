# 👟 HOKA Run Watcher

Surveille toutes les 15 minutes la page des runs du **HOKA Run Club Paris**
([eu-events.hoka.com/parisstorehub](https://eu-events.hoka.com/parisstorehub))
et envoie une notification sur ton iPhone via l'app **[ntfy](https://ntfy.sh)** :

- 🏃 **Nouveau run** publié (titre, date, magasin, statut des inscriptions) ;
- 🎟️ **Places dispo** : un run à venir passe de « complet / liste d'attente » à « inscriptions ouvertes ».

Toucher la notification ouvre directement la page d'inscription du run.

Deux façons de le faire tourner : **GitHub Actions** (gratuit, mais le site bloque souvent les serveurs de GitHub) ou **ton Mac / Raspberry Pi** (recommandé, voir plus bas).

## Installation (5 minutes)

### 1. Installer ntfy sur l'iPhone

1. Installe **ntfy** depuis l'App Store.
2. Ouvre l'app → **+** → choisis un nom de topic **long et impossible à deviner**,
   par exemple `hoka-runs-8f3k2q9x7m`. N'importe qui connaissant ce nom peut lire
   tes notifications, donc garde-le secret.
3. Autorise les notifications.

### 2. Configurer le dépôt GitHub

1. Fork ce dépôt (ou utilise-le directement si c'est le tien).
2. **Settings → Secrets and variables → Actions → New repository secret** :
   - Nom : `NTFY_TOPIC`
   - Valeur : ton nom de topic (ex. `hoka-runs-8f3k2q9x7m`)
3. Onglet **Actions** → active les workflows si GitHub le demande.
4. Ouvre **Surveillance runs HOKA Paris** → **Run workflow** pour un premier test.
   Tu dois recevoir « 👟 Surveillance HOKA activée » avec la liste des runs à venir.

Ensuite tout est automatique, toutes les 15 minutes.

## Comment ça marche

```
GitHub Actions (cron */15)
   └─ watch.py ouvre la page dans Chromium (Playwright)
        └─ lit la liste des runs que la page charge (JSON « getItems » du hub Splash)
             └─ compare avec state/state.json (runs déjà vus)
                  └─ nouveau run / places libérées → POST https://ntfy.sh → iPhone
```

- `state/state.json` est mis à jour et commité par le bot uniquement quand quelque chose change.
- Si la page ne fournit plus ce JSON (changement de site), le script se rabat sur les liens de la page.

## ⚠️ Anti-bot du site

Le site est protégé par **DataDome**, qui refuse parfois l'accès aux serveurs
(erreur 403). Lors des tests, environ un essai sur deux passait.
Le script ne contourne pas cette protection : il réessaie simplement au passage suivant.

- Un blocage ponctuel est ignoré en silence.
- Après **8 échecs d'affilée (2 h)**, tu reçois une alerte « ⚠️ Surveillance HOKA bloquée »,
  puis « ✅ rétablie » quand ça repasse.

Les serveurs de GitHub sont bloqués quasi systématiquement. La solution est de faire
la vérification **depuis ta connexion internet à la maison** (Mac ou Raspberry Pi
allumé), où le site te voit comme un visiteur normal.

### Installation sur ton Mac ou un Raspberry Pi

Ouvre le Terminal et colle (remplace le topic par le tien) :

```bash
git clone https://github.com/Sonico347/hoka-run-watcher.git ~/hoka-run-watcher
cd ~/hoka-run-watcher && ./install.sh hoka-runs-xxxxxxxxxxxx
```

Le script installe tout dans le dossier, fait un premier passage (tu dois recevoir
« 👟 Surveillance HOKA activée »), puis relance la vérification toutes les 15 minutes :
via `launchd` sur Mac, via `cron` sur Raspberry Pi / Linux.

- Journal : `~/.hoka-run-watcher/watch.log`
- Mettre à jour : `cd ~/hoka-run-watcher && git pull && ./install.sh hoka-runs-xxxxxxxxxxxx`
- Arrêter : `~/hoka-run-watcher/install.sh --uninstall`
- Sur Mac, aucune vérification n'a lieu pendant la mise en veille. Pour un Mac fixe :
  Réglages Système → Énergie → « Empêcher la suspension d'activité automatique lorsque l'écran est éteint ».

Une fois la version locale en place, désactive le workflow GitHub
(Actions → Surveillance runs HOKA Paris → `…` → **Disable workflow**) pour ne pas recevoir
l'alerte « bloquée » de GitHub.

## Réglages optionnels

| Variable | Où | Rôle |
|---|---|---|
| `NTFY_TOPIC` | Secret (obligatoire) | Topic ntfy de ton iPhone |
| `NTFY_SERVER` | Variable | Autre serveur ntfy (défaut `https://ntfy.sh`) |
| `WATCH_URL` | Env | Autre page hub à surveiller |
| `BLOCKED_ALERT_AFTER` | Env | Nb d'échecs d'affilée avant l'alerte (défaut 8) |

## Dépannage

Chaque exécution garde 3 jours un artefact **debug** (HTML, capture d'écran,
réponses JSON) dans l'onglet Actions, pour voir ce que le script a reçu.

## Licence

MIT
