# Snap caps monolithiques et lame-chargeur C96

Cartouches de manipulation inertes d'un seul tenant (douille + ogive, sans amorce) en 9x19,
8x22 Nambu et 5,6 mm GP90, et lame-chargeur 10 coups pour Mauser C96.

```
pip install cadquery
python snap_caps.py            # STEP + STL dans ./output
python snap_caps.py --help     # tolerances STL, dossier de sortie, profil JSON
python snap_cap_gp90.py        # 5,6 mm GP90 (Fass 90) : STEP + STL dans ./output
python ladestreifen_c96.py     # lame-chargeur Mauser C96 : STEP + STL dans ./output
python ladestreifen_c96_antiwarping.py   # meme lame, version anti-warping
```

- `snap_caps.py` : profil parametrique (droites + arcs exacts), revolution, percage de l'event, export.
- `apercu_3d.html` : apercu React + Three.js qui fait tourner le meme profil (coupe, rayon X).
- `snap_cap_gp90.py` : script autonome pour le 5,6 mm GP90, avec `tolerance_diametre` en tete de fichier
  et maillage STL a 0,005 mm / 2 deg.
- `apercu_gp90.html` : apercu du GP90 sur le meme principe.
- `ladestreifen_c96.py` : lame-chargeur 10 coups pour Mauser C96, imprimee a plat sur le dos ;
  `tolerance_glissiere` et `epaisseur_dos` en tete de fichier.
- `apercu_ladestreifen.html` : apercu de la lame avec une cartouche 9x19 temoin et sa coupe YZ.
- `ladestreifen_c96_antiwarping.py` : meme lame avec chanfreins de pied d'elephant, rainures de
  relaxation sous la semelle et oreilles d'ancrage cassables (`activer_mouse_ears`,
  `activer_rainures_retrait`).
- `apercu_ladestreifen_antiwarping.html` : apercu de cette version, vue de dessous comprise.
- `output/` : exports generes avec les tolerances par defaut de chaque script.
