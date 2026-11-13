# Snap caps monolithiques 9x19 et 8x22 Nambu

Cartouches de manipulation inertes d'un seul tenant (douille + ogive, sans amorce).

```
pip install cadquery
python snap_caps.py            # STEP + STL dans ./output
python snap_caps.py --help     # tolerances STL, dossier de sortie, profil JSON
```

- `snap_caps.py` : profil parametrique (droites + arcs exacts), revolution, percage de l'event, export.
- `apercu_3d.html` : apercu React + Three.js qui fait tourner le meme profil (coupe, rayon X).
- `output/` : exports generes avec les tolerances par defaut (0,002 mm / 0,05 rad).
