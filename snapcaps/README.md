# Snap caps monolithiques 9x19, 8x22 Nambu et 5,6 mm GP90

Cartouches de manipulation inertes d'un seul tenant (douille + ogive, sans amorce).

```
pip install cadquery
python snap_caps.py            # STEP + STL dans ./output
python snap_caps.py --help     # tolerances STL, dossier de sortie, profil JSON
python snap_cap_gp90.py        # 5,6 mm GP90 (Fass 90) : STEP + STL dans ./output
```

- `snap_caps.py` : profil parametrique (droites + arcs exacts), revolution, percage de l'event, export.
- `apercu_3d.html` : apercu React + Three.js qui fait tourner le meme profil (coupe, rayon X).
- `snap_cap_gp90.py` : script autonome pour le 5,6 mm GP90, avec `tolerance_diametre` en tete de fichier
  et maillage STL a 0,005 mm / 2 deg.
- `apercu_gp90.html` : apercu du GP90 sur le meme principe.
- `output/` : exports generes avec les tolerances par defaut de chaque script.
