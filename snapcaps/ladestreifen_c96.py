#!/usr/bin/env python3
"""Lame-chargeur (Ladestreifen) 10 coups pour Mauser C96, imprimee a plat.

Piece polymere (ASA-X) pour 9x19 mm Parabellum et 7,63x25 mm Mauser, concue
pour etre imprimee a plat sur le dos, sans support :
  - X = longueur de la lame, Y = largeur, Z = hauteur ;
  - Z = 0 est la face externe du dos, posee sur le plateau ;
  - le dessous des levres de retention est une pente a 45 deg auto-portante.

Usage :
    pip install cadquery
    python ladestreifen_c96.py                 # STEP + STL dans ./output
    python ladestreifen_c96.py --outdir build
    python ladestreifen_c96.py --profil-json   # sections 2D seules (sans CadQuery)

La section transversale ne depend que de l'ecartement des levres ; le solide
est un lissage regle (loft) de cette section le long de X, ou l'ecartement
se resserre aux deux extremites. L'apercu Three.js relie les memes sections.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# ==========================================================================
# PARAMETRES
# ==========================================================================
# Jeu d'ajustement dans les rainures du boitier-culasse du C96, applique aux
# largeurs exterieures (dos et flancs superieurs).
tolerance_glissiere = -0.08
# Epaisseur de la semelle posee sur le plateau. Les hauteurs ci-dessous sont
# comptees depuis le dessus du dos, pour que l'ajustement de la cartouche ne
# change pas si cette epaisseur est modifiee.
epaisseur_dos = 1.20

NOM_FICHIER = "ladestreifen_mauser_c96_10coups_plat"

# --- Longueur (axe X) -----------------------------------------------------
LONGUEUR = 101.50
CAPACITE = 10

# --- Section transversale (plan YZ) ---------------------------------------
LARGEUR_DOS = 13.40          # largeur du dos (+ tolerance_glissiere)
LARGEUR_FLANCS = 11.80       # largeur exterieure des ailes (+ tolerance_glissiere)
HAUTEUR_AILES = 3.40         # ailes au-dessus du dos (hauteur totale 4,60)
ECART_BOURRELET = 10.15      # passage libre du culot entre les ailes
HAUTEUR_BOURRELET = 1.40     # hauteur du passage du culot (Z 1,20 a 2,60)
ECART_LEVRES = 8.65          # ecartement libre entre les levres
ANGLE_PENTE = 45.0           # dessous des levres, mesure depuis l'horizontale
CONGE = 0.40                 # conge interne a la jonction dos / ailes

# Degagement du haut des levres. Avec des levres verticales jusqu'en haut, les
# 0,5 mm superieurs entrent dans le chanfrein de gorge de l'etui (0,35 mm par
# cote sur la cartouche temoin). Les levres gardent donc une portee verticale
# de cette hauteur, puis s'ouvrent en chanfrein vers le haut (face tournee vers
# le ciel : aucun surplomb). None = levres verticales jusqu'en haut, comme au
# cahier des charges.
PORTEE_LEVRES = 0.40
ANGLE_DEGAGEMENT = 45.0      # mesure depuis la verticale

# --- Retention d'extremite (axe X) ----------------------------------------
ECART_EXTREMITE = 8.10       # ecartement resserre des levres
ANGLE_RAMPE = 30.0           # rampe laterale, mesuree depuis l'axe X
LONGUEUR_RETENTION = 1.20    # longueur totale : chanfrein + palier + rampe
CHANFREIN_ENTREE = 0.50      # chanfrein d'entree, 45 deg

# --- Cartouche temoin 9x19 (controle d'ajustement uniquement) -------------
TEMOIN_D_CULOT = 9.96
TEMOIN_EP_BOURRELET = 1.27
TEMOIN_D_GORGE = 8.40
TEMOIN_LARGEUR_GORGE = 1.45
TEMOIN_ANGLE_GORGE = 35.0    # chanfrein de gorge, mesure depuis l'axe
TEMOIN_D_CORPS = 9.93

# --- Maillage STL ---------------------------------------------------------
STL_DEVIATION_LINEAIRE = 0.005   # mm
STL_DEVIATION_ANGULAIRE = 2.0    # deg

Pt = tuple[float, float]  # (y, z)


# ==========================================================================
# GEOMETRIE 2D (aucune dependance)
# ==========================================================================
def cotes() -> dict:
    """Cotes derivees des parametres."""
    demi_levres, demi_bout = ECART_LEVRES / 2, ECART_EXTREMITE / 2
    rampe = (demi_levres - demi_bout) / math.tan(math.radians(ANGLE_RAMPE))
    palier = LONGUEUR_RETENTION - CHANFREIN_ENTREE - rampe
    if palier < 0:
        raise ValueError("LONGUEUR_RETENTION trop courte pour le chanfrein et la rampe")
    return {
        "demi_dos": (LARGEUR_DOS + tolerance_glissiere) / 2,
        "demi_flancs": (LARGEUR_FLANCS + tolerance_glissiere) / 2,
        "demi_bourrelet": ECART_BOURRELET / 2,
        "demi_levres": demi_levres, "demi_bout": demi_bout,
        "hauteur": epaisseur_dos + HAUTEUR_AILES,
        "z_levres": epaisseur_dos + HAUTEUR_BOURRELET,
        "rampe": rampe, "palier": palier,
    }


def profil_levre(w: float) -> list[Pt]:
    """Face interne d'une levre d'ecartement 2w, du bas vers le haut."""
    c = cotes()
    z_pente = c["z_levres"] + (c["demi_bourrelet"] - w) * math.tan(math.radians(ANGLE_PENTE))
    pts: list[Pt] = [(c["demi_bourrelet"], c["z_levres"]), (w, z_pente)]
    if PORTEE_LEVRES is None:
        pts.append((w, c["hauteur"]))
    else:
        z_deg = z_pente + PORTEE_LEVRES
        y_haut = w + (c["hauteur"] - z_deg) * math.tan(math.radians(ANGLE_DEGAGEMENT))
        if z_deg >= c["hauteur"] or y_haut > c["demi_flancs"] - 0.2:
            raise ValueError("degagement des levres incompatible avec la hauteur des ailes")
        pts += [(w, z_deg), (y_haut, c["hauteur"])]
    return pts


def demi_section(w: float) -> tuple[list[Pt], Pt]:
    """Demi-section cote +Y : sommets du plateau au fond du canal, dans le
    sens anti-horaire, et point milieu du conge (entre les deux derniers)."""
    c = cotes()
    pts: list[Pt] = [(c["demi_dos"], 0.0), (c["demi_dos"], epaisseur_dos),
                     (c["demi_flancs"], epaisseur_dos), (c["demi_flancs"], c["hauteur"])]
    pts += reversed(profil_levre(w))
    centre = (c["demi_bourrelet"] - CONGE, epaisseur_dos + CONGE)
    pts += [(c["demi_bourrelet"], epaisseur_dos + CONGE), (centre[0], epaisseur_dos)]
    k = CONGE * math.sqrt(0.5)
    return pts, (centre[0] + k, centre[1] - k)


def stations() -> list[tuple[float, float]]:
    """(x, demi-ecartement des levres) : chanfrein d'entree, palier resserre,
    rampe a 30 deg, partie courante, puis l'extremite symetrique."""
    c = cotes()
    debut = [(0.0, c["demi_bout"] + CHANFREIN_ENTREE),
             (CHANFREIN_ENTREE, c["demi_bout"]),
             (CHANFREIN_ENTREE + c["palier"], c["demi_bout"]),
             (LONGUEUR_RETENTION, c["demi_levres"])]
    if c["palier"] < 1e-9:
        del debut[2]
    return debut + [(LONGUEUR - x, w) for x, w in reversed(debut)]


def rayon_temoin(z: float) -> float:
    """Rayon exterieur de la cartouche temoin a la hauteur z au-dessus du culot."""
    r_gorge, r_corps = TEMOIN_D_GORGE / 2, TEMOIN_D_CORPS / 2
    z_gorge = TEMOIN_EP_BOURRELET + TEMOIN_LARGEUR_GORGE
    if z <= TEMOIN_EP_BOURRELET:
        return TEMOIN_D_CULOT / 2
    if z <= z_gorge:
        return r_gorge
    return min(r_corps, r_gorge + (z - z_gorge) * math.tan(math.radians(TEMOIN_ANGLE_GORGE)))


def demi_ecart_levre(z: float, profil: list[Pt]) -> float:
    """Demi-ecartement libre entre les levres a la hauteur z."""
    for (y0, z0), (y1, z1) in zip(profil, profil[1:]):
        if z0 <= z <= z1:
            return y0 if z1 == z0 else y0 + (y1 - y0) * (z - z0) / (z1 - z0)
    return profil[-1][0]


def ajustement() -> dict:
    """Jeux entre la lame (partie courante) et la cartouche temoin, culot pose
    sur le dos : valeurs par cote, negatives en cas d'interference."""
    c = cotes()
    profil = profil_levre(c["demi_levres"])
    r_culot = TEMOIN_D_CULOT / 2
    pas = [c["z_levres"] + i * 0.001 for i in range(int((c["hauteur"] - c["z_levres"]) / 0.001) + 1)]
    # Au-dessus du bourrelet uniquement : le bourrelet est retenu par la pente.
    haut = [z for z in pas if z - epaisseur_dos > TEMOIN_EP_BOURRELET + 1e-9]
    jeu_etui = min(demi_ecart_levre(z, profil) - rayon_temoin(z - epaisseur_dos) for z in haut)
    z_contact = c["z_levres"] + (c["demi_bourrelet"] - r_culot) * math.tan(math.radians(ANGLE_PENTE))
    # Butee d'extremite : la gorge (cercle) vient contre l'arete du palier.
    r_gorge = TEMOIN_D_GORGE / 2
    x_butee = (CHANFREIN_ENTREE + c["palier"]
               + math.sqrt(max(0.0, r_gorge**2 - c["demi_bout"] ** 2)))
    return {
        "engagement_levres": r_culot - c["demi_levres"],
        "jeu_lateral_culot": c["demi_bourrelet"] - r_culot,
        "jeu_axial_culot": z_contact - (epaisseur_dos + TEMOIN_EP_BOURRELET),
        "jeu_levres_gorge": c["demi_levres"] - r_gorge,
        "jeu_mini_levres_etui": jeu_etui,
        "paroi_ailes": c["demi_flancs"] - c["demi_bourrelet"],
        "serrage_extremite": r_gorge - c["demi_bout"],
        "depassement_extremite": r_culot - x_butee,
        "jeu_cumule_x": (LONGUEUR - 2 * x_butee) - (CAPACITE - 1) * TEMOIN_D_CULOT,
    }


def controles() -> list[str]:
    """Remarques a afficher avant l'export."""
    c, a, notes = cotes(), ajustement(), []
    if ANGLE_PENTE < 45 - 1e-9:
        notes.append(f"pente des levres a {ANGLE_PENTE:g} deg : surplomb non auto-portant")
    if a["jeu_mini_levres_etui"] < 0:
        notes.append(f"interference levres / etui de {-a['jeu_mini_levres_etui']:.2f} mm par cote "
                     "(regler PORTEE_LEVRES)")
    if PORTEE_LEVRES is not None:
        notes.append(f"degagement du haut des levres ajoute (portee verticale {PORTEE_LEVRES:g} mm) ; "
                     "PORTEE_LEVRES = None pour des levres verticales jusqu'en haut")
    notes.append(f"rampe d'extremite : {c['rampe']:.2f} mm a {ANGLE_RAMPE:g} deg, palier "
                 f"{c['palier']:.2f} mm, chanfrein {CHANFREIN_ENTREE:g} mm "
                 f"(total {LONGUEUR_RETENTION:g} mm)")
    if a["paroi_ailes"] < 0.8:
        notes.append(f"paroi des ailes au niveau du bourrelet : {a['paroi_ailes']:.3f} mm")
    return notes


# ==========================================================================
# SOLIDE CADQUERY
# ==========================================================================
def fil_section(x: float, w: float):
    """Contour ferme de la section a l'abscisse x (plan YZ)."""
    import cadquery as cq

    droite, milieu = demi_section(w)
    gauche = [(-y, z) for y, z in reversed(droite)]
    wp = cq.Workplane("YZ", origin=(x, 0, 0)).moveTo(*droite[0])
    for p in droite[1:-1]:
        wp = wp.lineTo(*p)
    wp = wp.threePointArc(milieu, droite[-1])      # conge cote +Y
    wp = wp.lineTo(*gauche[0])                     # fond du canal
    wp = wp.threePointArc((-milieu[0], milieu[1]), gauche[1])  # conge cote -Y
    for p in gauche[2:]:
        wp = wp.lineTo(*p)
    return wp.close().val()


def construire():
    """Lissage regle des sections : faces planes entre stations."""
    import cadquery as cq

    fils = [fil_section(x, w) for x, w in stations()]
    return cq.Workplane("XY").add(cq.Solid.makeLoft(fils, ruled=True))


def exporter(dossier: Path) -> None:
    import cadquery as cq

    for note in controles():
        print(f"  ! {note}")
    modele = construire()
    solide = modele.val()
    if not solide.isValid():
        raise RuntimeError("solide invalide")
    boite, a = solide.BoundingBox(), ajustement()
    print(f"  enveloppe {boite.xlen:.2f} x {boite.ylen:.2f} x {boite.zlen:.2f} mm, "
          f"volume {solide.Volume():.1f} mm3")
    print(f"  engagement des levres {a['engagement_levres']:.3f} mm par cote, "
          f"jeu axial du culot {a['jeu_axial_culot']:.3f} mm")
    print(f"  jeu mini levres / etui {a['jeu_mini_levres_etui']:+.3f} mm par cote")
    print(f"  extremites : serrage {a['serrage_extremite']:.2f} mm par cote, depassement "
          f"possible {a['depassement_extremite']:.2f} mm, jeu cumule en X {a['jeu_cumule_x']:.2f} mm")
    dossier.mkdir(parents=True, exist_ok=True)
    step, stl = dossier / f"{NOM_FICHIER}.step", dossier / f"{NOM_FICHIER}.stl"
    cq.exporters.export(modele, str(step))
    cq.exporters.export(modele, str(stl), tolerance=STL_DEVIATION_LINEAIRE,
                        angularTolerance=math.radians(STL_DEVIATION_ANGULAIRE))
    print(f"  -> {step}\n  -> {stl}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", type=Path, default=Path(__file__).parent / "output")
    ap.add_argument("--profil-json", action="store_true",
                    help="affiche les sections 2D et les jeux, sans export")
    args = ap.parse_args()
    if args.profil_json:
        print(json.dumps({"stations": [{"x": x, "w": w, "demi_section": demi_section(w)[0]}
                                       for x, w in stations()],
                          "cotes": cotes(), "ajustement": ajustement()}, indent=1))
        return
    print(f"Ladestreifen Mauser C96, {CAPACITE} coups (tolerance_glissiere = "
          f"{tolerance_glissiere:+.2f} mm, epaisseur_dos = {epaisseur_dos:.2f} mm)")
    exporter(args.outdir)


if __name__ == "__main__":
    main()
