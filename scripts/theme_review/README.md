# Revue des thèmes web

Outils pour contrôler les 34 thèmes de l'interface web dans les 3 modes (clair, sombre, contraste élevé), sur le vrai rendu de l'application. Ils partagent avec les tests (`tests/theme_probe.py`) les mêmes données fictives et la même définition des mesures.

## Avant de modifier un thème ou le CSS partagé

```
python scripts/theme_review/capture.py --metrics=avant.json
python scripts/theme_review/capture.py --out=%TEMP%\t2k_avant
```

## Après

```
python scripts/theme_review/capture.py --metrics=apres.json
python scripts/theme_review/compare_metrics.py avant.json apres.json
python scripts/theme_review/capture.py --out=%TEMP%\t2k_apres
python scripts/theme_review/pairs.py %TEMP%\t2k_avant %TEMP%\t2k_apres %TEMP%\t2k_planches
```

`compare_metrics.py` liste les régressions (une combinaison thème × mode qui passait et échoue, ou un contraste qui baisse de plus de 0,3) et tout ce qui échoue encore. Les planches montrent, pour chaque thème, mode et vue, la référence à gauche et le nouveau rendu à droite, avec la part de pixels modifiés.

Options de `capture.py` : `--only=<thème>` (répétable) limite aux thèmes cités ; `--view=<vue>` (répétable) aux vues citées (`profile_audio` montre le curseur de volume) ; `--resume` reprend une capture interrompue. Pour lancer plusieurs captures en parallèle, donner à chacune son port et son dossier de données : `T2K_DEVTOOLS_PORT=9301 T2K_SHOTS_DATADIR=…`.

## Garde-fous automatiques (pytest)

- `tests/test_theme_css_integrity.py` : aucun commentaire CSS fermé trop tôt, accolades équilibrées, jetons obligatoires présents.
- `tests/test_theme_readability.py` : contrastes, largeurs et état des contrôles mesurés dans la page, pour chaque thème et chaque mode ; bloc sombre réellement appliqué.
- `tests/test_theme_visual_regression.py` : rendu de la page Ajout comparé aux références `tests/fixtures/theme_snapshots/`, dans les 3 modes. Pour accepter un changement voulu, supprimer la référence concernée et relancer deux fois.
