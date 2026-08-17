# premiere-pr

Ce depot sert de bac a sable pour apprendre le workflow Git/GitHub : commits, branches, et pull requests.

## Objectif

Un espace simple pour experimenter avec des changements de code et des revues de pull request.

## Installation silencieuse (Torrent 2000)

L'installeur Windows de Torrent 2000 (Inno Setup) supporte l'installation silencieuse standard :

```
Torrent2000-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Sans argument `/TASKS` ni `/MERGETASKS`, les 3 tâches (icône bureau, association `.torrent`, association `magnet:`) restent sélectionnées par défaut -- ce qui peut surprendre un déploiement scripté qui n'en veut pas. Pour les choisir explicitement :

- `/TASKS="desktopicon,associatetorrent,associatemagnet"` -- liste positive : seules les tâches nommées sont sélectionnées, les autres sont désélectionnées.
- `/MERGETASKS="!associatetorrent,!associatemagnet"` -- désélectionne les tâches nommées (préfixe `!`) tout en gardant les autres, par exemple `desktopicon`, à leur valeur par défaut.

Détail complet : voir `packaging/torrent2000_installer.iss`.
