#!/usr/bin/env python3
"""Cartouche de manipulation (snap cap) monolithique 5,6 mm GP90 pour Fass 90.

Piece inerte d'un seul tenant (douille + ogive, sans amorce), calibre
5,6 mm GP90 / 5.56x45 mm, destinee au Fass 90 (Stgw 90 / SIG SG 550).
Le logement d'amorce recoit un bouchon de mastic retenu par une gorge en
contre-depouille ; un event purge l'air vers la gorge d'extraction.

Usage :
    pip install cadquery
    python snap_cap_gp90.py                 # STEP + STL dans ./output
    python snap_cap_gp90.py --outdir build
    python snap_cap_gp90.py --profil-json   # profil 2D seul (sans CadQuery)

Conventions : unites en mm, axe de revolution = Z, culot en Z = 0.
Le profil est decrit dans le demi-plan (r, z) par des droites et des arcs
exacts ; l'apercu Three.js fait tourner ce meme profil.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# ==========================================================================
# PARAMETRES
# ==========================================================================
# Jeu applique aux diametres exterieurs de la douille et du culot
# (R1, P1, P2, H1, H2). Le fond de gorge et l'ogive restent a leur cote.
tolerance_diametre = -0.05

NOM_FICHIER = "snap_cap_56mm_gp90_fass90"

# --- Culot et gorge d'extraction ------------------------------------------
D_CULOT = 9.58            # R1, diametre du culot
EP_BOURRELET = 1.14       # R, epaisseur du bourrelet
CHANFREIN_CULOT = 0.30    # chanfrein inferieur, 45 deg
D_FOND_GORGE = 8.43       # diametre au fond de la gorge
LARGEUR_GORGE = 1.70      # largeur du fond de gorge, juste au-dessus du bourrelet
ANGLE_GORGE = 35.0        # chanfrein cote corps, mesure depuis le plan
                          # perpendiculaire a l'axe (il finit ainsi sous Z_P1)

# --- Corps de douille bouteille -------------------------------------------
Z_P1 = 3.30               # cote ou se mesure P1
D_P1 = 9.55               # P1, diametre a la base du corps
Z_EPAULEMENT = 36.57      # L1, debut de l'epaulement
D_P2 = 9.00               # P2, diametre au debut de l'epaulement
ANGLE_EPAULEMENT = 23.0   # demi-angle de l'epaulement, depuis l'axe
Z_COLLET_SPEC = 40.35     # L2 demande au cahier des charges
# Les cotes L1, P2, H1 et l'angle de 23 deg fixent L2 = 39,60 mm ; un L2 de
# 40,35 mm donnerait un epaulement a 18,8 deg qui buterait dans la chambre
# avant le verrouillage. True : l'angle pilote. False : Z_COLLET_SPEC pilote.
EPAULEMENT_PAR_ANGLE = True
D_H1 = 6.43               # H1, diametre exterieur a la base du collet
D_H2 = 6.43               # H2, diametre exterieur aux levres
L_DOUILLE = 44.70         # L3, longueur de douille (plan des levres)
CONGE = 0.50              # conges corps/epaulement et epaulement/collet

# --- Ogive ----------------------------------------------------------------
D_OGIVE = 5.69            # diametre de l'ogive aux levres (.224")
OAL = 57.20               # L6, longueur totale
R_OGIVE = 38.0            # rayon d'ogive ; None = ogive tangente calculee
R_POINTE = 0.65           # rayon de la pointe arrondie

# --- Logement d'amorce, ancrage et event ----------------------------------
D_PUITS = 4.45            # diametre du puits (Small Rifle)
PROF_PUITS = 3.30         # profondeur du puits
CHANFREIN_PUITS = 0.30    # chanfrein d'entree, 45 deg
Z_ANCRAGE = 2.00          # profondeur du debut de la gorge d'ancrage
SUR_RAYON_ANCRAGE = 0.35  # sur-rayon de la gorge (diametre local 5,15)
H_ANCRAGE = 0.80          # hauteur de la gorge d'ancrage
D_EVENT = 1.00            # diametre de l'event

# --- Maillage STL ---------------------------------------------------------
STL_DEVIATION_LINEAIRE = 0.005   # mm
STL_DEVIATION_ANGULAIRE = 2.0    # deg

Pt = tuple[float, float]  # (r, z)


# ==========================================================================
# GEOMETRIE 2D (aucune dependance)
# ==========================================================================
def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def _mul(a: Pt, k: float) -> Pt:
    return (a[0] * k, a[1] * k)


def _unit(a: Pt) -> Pt:
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n)


def _arc(depart: Pt, fin: Pt, centre: Pt, rayon: float) -> dict:
    """Arc < 180 deg ; le point milieu sert a threePointArc."""
    bis = _unit(_add(_sub(depart, centre), _sub(fin, centre)))
    return {"t": "A", "p": fin, "mid": _add(centre, _mul(bis, rayon)),
            "c": centre, "r": rayon, "from": depart}


def _conge(avant: Pt, sommet: Pt, apres: Pt, rayon: float) -> tuple[Pt, Pt, Pt]:
    """Conge tangent aux deux segments : (entree, sortie, centre)."""
    v1, v2 = _unit(_sub(avant, sommet)), _unit(_sub(apres, sommet))
    demi = math.acos(max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1]))) / 2
    recul = rayon / math.tan(demi)
    bis = _unit(_add(v1, v2))
    return (_add(sommet, _mul(v1, recul)), _add(sommet, _mul(v2, recul)),
            _add(sommet, _mul(bis, rayon / math.sin(demi))))


def r_ext(diametre: float) -> float:
    """Rayon d'un diametre exterieur de douille ou de culot, jeu applique."""
    return (diametre + tolerance_diametre) / 2


def cotes_derivees() -> dict:
    """Cotes calculees a partir des parametres."""
    r_gorge, r_p1, r_p2 = D_FOND_GORGE / 2, r_ext(D_P1), r_ext(D_P2)
    r_h1, r_ogive = r_ext(D_H1), D_OGIVE / 2

    # Chanfrein de gorge : il monte jusqu'au cone du corps (droite P1-P2).
    z_gorge_haut = EP_BOURRELET + LARGEUR_GORGE
    pente_corps = (r_p2 - r_p1) / (Z_EPAULEMENT - Z_P1)
    pente_chanfrein = 1 / math.tan(math.radians(ANGLE_GORGE))
    z_corps = ((r_p1 - pente_corps * Z_P1 - r_gorge + pente_chanfrein * z_gorge_haut)
               / (pente_chanfrein - pente_corps))
    r_corps = r_p1 + pente_corps * (z_corps - Z_P1)

    # Epaulement : pilote par l'angle officiel ou par la cote L2 demandee.
    if EPAULEMENT_PAR_ANGLE:
        z_collet = Z_EPAULEMENT + (r_p2 - r_h1) / math.tan(math.radians(ANGLE_EPAULEMENT))
    else:
        z_collet = Z_COLLET_SPEC
    angle_epaulement = math.degrees(math.atan2(r_p2 - r_h1, z_collet - Z_EPAULEMENT))

    # Ogive : arc de rayon R_OGIVE passant par le bord de l'ogive aux levres
    # et tangent a la sphere de pointe (intersection de deux cercles).
    base: Pt = (r_ogive, L_DOUILLE)
    c_pointe: Pt = (0.0, OAL - R_POINTE)
    if R_OGIVE is None:  # ogive tangente : centre a la hauteur des levres
        longueur = OAL - L_DOUILLE
        rho = ((r_ogive**2 + (longueur - R_POINTE) ** 2 - R_POINTE**2)
               / (2 * (r_ogive - R_POINTE)))
        c_ogive: Pt = (r_ogive - rho, L_DOUILLE)
    else:
        rho = R_OGIVE
        d = math.hypot(*_sub(c_pointe, base))
        a = (rho**2 - (rho - R_POINTE) ** 2 + d**2) / (2 * d)
        if rho <= a:
            raise ValueError("R_OGIVE trop petit pour cette longueur d'ogive")
        h = math.sqrt(rho**2 - a**2)
        u = _unit(_sub(c_pointe, base))
        pied = _add(base, _mul(u, a))
        c_ogive = min((_add(pied, _mul((-u[1], u[0]), s * h)) for s in (1, -1)),
                      key=lambda c: c[0])  # centre du cote oppose de l'axe
    raccord = _add(c_ogive, _mul(_unit(_sub(c_pointe, c_ogive)), rho))
    angle_base = math.degrees(math.asin((base[1] - c_ogive[1]) / rho))

    # Event : droite inclinee du fond du puits au milieu du fond de gorge.
    a_ev: Pt = (D_PUITS / 2 - D_EVENT / 2, PROF_PUITS)
    b_ev: Pt = (r_gorge, EP_BOURRELET + LARGEUR_GORGE / 2)
    inclinaison = math.atan2(a_ev[1] - b_ev[1], b_ev[0] - a_ev[0])
    demi_trace = D_EVENT / 2 / math.cos(inclinaison)
    return {
        "z_gorge_haut": z_gorge_haut, "z_corps": z_corps, "r_corps": r_corps,
        "z_collet": z_collet, "angle_epaulement": angle_epaulement,
        "feuillure": r_ext(D_H2) - r_ogive,
        "r_ogive": rho, "c_ogive": c_ogive, "c_pointe": c_pointe,
        "raccord_pointe": raccord, "angle_base_ogive": angle_base,
        "event_a": a_ev, "event_b": b_ev, "event_inclinaison": math.degrees(inclinaison),
        "event_sortie_z": (b_ev[1] - demi_trace, b_ev[1] + demi_trace),
        "ancrage_z": (Z_ANCRAGE, Z_ANCRAGE + H_ANCRAGE),
        "d_ancrage": D_PUITS + 2 * SUR_RAYON_ANCRAGE,
    }


def profil() -> tuple[Pt, list[dict]]:
    """Profil ferme (demi-coupe) : point de depart + segments 'L' / 'A'."""
    d = cotes_derivees()
    rp, r_culot, r_gorge = D_PUITS / 2, r_ext(D_CULOT), D_FOND_GORGE / 2
    r_ogive = D_OGIVE / 2
    depart: Pt = (rp + CHANFREIN_PUITS, 0.0)
    segs: list[dict] = []

    def droite(pt: Pt) -> None:
        segs.append({"t": "L", "p": pt})

    # Culot et gorge d'extraction
    droite((r_culot - CHANFREIN_CULOT, 0.0))
    droite((r_culot, CHANFREIN_CULOT))
    droite((r_culot, EP_BOURRELET))
    droite((r_gorge, EP_BOURRELET))
    droite((r_gorge, d["z_gorge_haut"]))
    # Corps, epaulement et collet, avec conges aux deux transitions
    corps: list[Pt] = [(d["r_corps"], d["z_corps"]), (r_ext(D_P2), Z_EPAULEMENT),
                       (r_ext(D_H1), d["z_collet"]), (r_ext(D_H2), L_DOUILLE)]
    droite(corps[0])
    for i in (1, 2):
        t1, t2, centre = _conge(corps[i - 1], corps[i], corps[i + 1], CONGE)
        droite(t1)
        segs.append(_arc(t1, t2, centre, CONGE))
    droite(corps[3])
    # Decrochement net aux levres, ogive puis pointe arrondie
    droite((r_ogive, L_DOUILLE))
    segs.append(_arc((r_ogive, L_DOUILLE), d["raccord_pointe"], d["c_ogive"], d["r_ogive"]))
    segs.append(_arc(d["raccord_pointe"], (0.0, OAL), d["c_pointe"], R_POINTE))
    # Retour par l'axe, puits d'amorce et gorge d'ancrage
    z0, z1 = d["ancrage_z"]
    ra = rp + SUR_RAYON_ANCRAGE
    for pt in [(0.0, PROF_PUITS), (rp, PROF_PUITS), (rp, z1), (ra, z1),
               (ra, z0), (rp, z0), (rp, CHANFREIN_PUITS)]:
        droite(pt)
    return depart, segs


def controles() -> list[str]:
    """Controles de coherence ; renvoie les remarques a afficher."""
    d, notes = cotes_derivees(), []
    bas, haut = d["event_sortie_z"]
    if bas <= EP_BOURRELET or haut >= d["z_gorge_haut"]:
        raise ValueError(f"l'event deborde du fond de gorge ({bas:.2f}..{haut:.2f} mm)")
    if d["z_corps"] > Z_P1:
        raise ValueError(f"le chanfrein de gorge finit a Z {d['z_corps']:.2f}, au-dessus de P1")
    if d["ancrage_z"][1] > PROF_PUITS - 0.3:
        raise ValueError("gorge d'ancrage trop proche du fond du puits")
    if abs(d["z_collet"] - Z_COLLET_SPEC) > 1e-6:
        notes.append(
            f"L2 = {d['z_collet']:.2f} mm (epaulement a {ANGLE_EPAULEMENT:g} deg) ; les "
            f"{Z_COLLET_SPEC:.2f} mm demandes donneraient un epaulement a "
            f"{math.degrees(math.atan2(r_ext(D_P2) - r_ext(D_H1), Z_COLLET_SPEC - Z_EPAULEMENT)):.1f} deg")
    elif abs(d["angle_epaulement"] - ANGLE_EPAULEMENT) > 0.05:
        notes.append(f"epaulement a {d['angle_epaulement']:.1f} deg au lieu de "
                     f"{ANGLE_EPAULEMENT:g} deg : risque de non-verrouillage")
    if abs(d["angle_base_ogive"]) > 0.01:
        notes.append(f"ogive secante R {d['r_ogive']:g} : angle de {d['angle_base_ogive']:.2f} deg "
                     "avec l'axe au plan des levres")
    return notes


# ==========================================================================
# SOLIDE CADQUERY
# ==========================================================================
def construire():
    """Revolution du profil puis percage de l'event."""
    import cadquery as cq

    depart, segs = profil()
    wp = cq.Workplane("XZ").moveTo(*depart)
    for s in segs:
        wp = wp.lineTo(*s["p"]) if s["t"] == "L" else wp.threePointArc(s["mid"], s["p"])
    corps = wp.close().revolve(360, (0, 0, 0), (0, 1, 0))

    # Event : percage incline dans le plan XZ (cote +X). L'outil est borne par
    # le plan du fond du puits (pas d'entaille au-dessus) et par le cylindre
    # du fond de gorge (il ne touche ni le bourrelet ni le chanfrein).
    d = cotes_derivees()
    a, b = d["event_a"], d["event_b"]
    u = _unit(_sub(b, a))
    origine = _sub(a, _mul(u, 3.0))
    longueur = math.hypot(*_sub(b, a)) + 5.0
    outil = cq.Solid.makeCylinder(D_EVENT / 2, longueur,
                                  cq.Vector(origine[0], 0, origine[1]),
                                  cq.Vector(u[0], 0, u[1]))
    limite = cq.Solid.makeCylinder(D_FOND_GORGE / 2 + 0.02, PROF_PUITS,
                                   cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
    return corps.cut(outil.intersect(limite))


def exporter(dossier: Path) -> None:
    import cadquery as cq

    for note in controles():
        print(f"  ! {note}")
    modele = construire()
    solide = modele.val()
    if not solide.isValid():
        raise RuntimeError("solide invalide")
    boite, d = solide.BoundingBox(), cotes_derivees()
    print(f"  chanfrein de gorge jusqu'a Z {d['z_corps']:.3f}, collet a Z {d['z_collet']:.3f}")
    print(f"  feuillure aux levres {d['feuillure']:.3f} mm, "
          f"event incline de {d['event_inclinaison']:.1f} deg")
    print(f"  enveloppe d {boite.xlen:.3f} x L {boite.zlen:.3f} mm, "
          f"volume {solide.Volume():.1f} mm3")
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
                    help="affiche le profil 2D et les cotes derivees, sans export")
    args = ap.parse_args()
    if args.profil_json:
        depart, segs = profil()
        print(json.dumps({"start": depart, "segments": segs,
                          "derived": cotes_derivees()}, indent=1))
        return
    print(f"5,6 mm GP90 (tolerance_diametre = {tolerance_diametre:+.2f} mm)")
    exporter(args.outdir)


if __name__ == "__main__":
    main()
