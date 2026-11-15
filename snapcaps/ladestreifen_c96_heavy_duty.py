#!/usr/bin/env python3
"""Lame-chargeur (Ladestreifen) 10 coups pour Mauser C96, version haute resistance.

Piece polymere (ASA-X) pour 9x19 mm Parabellum et 7,63x25 mm Mauser, a section
etagee, imprimee a plat sur le dos sans support :
  - X = longueur de la lame, Y = largeur, Z = hauteur, Z = 0 sur le plateau ;
  - pied d'insertion (X = 0 a longueur_pied_c96) a l'encombrement du C96 ;
  - transition en rampe, qui sert de butee contre le haut du boitier ;
  - corps renforce jusqu'au bout, hors de l'arme, aux parois massives ;
  - guidage interne des cartouches identique d'un bout a l'autre : meme plan
    d'appui des culots, meme couloir, memes levres.

Usage :
    pip install cadquery
    python ladestreifen_c96_heavy_duty.py                 # STEP + STL dans ./output
    python ladestreifen_c96_heavy_duty.py --outdir build
    python ladestreifen_c96_heavy_duty.py --profil-json   # sections 2D seules (sans CadQuery)

Construction : l'enveloppe exterieure est un polyedre a faces planes passant
par quatre sections (debut et fin du pied, debut et fin du corps) ; le guidage
interne est un lissage regle retire de cette enveloppe ; les rainures sont
ensuite retirees et les oreilles ajoutees. L'apercu Three.js relie les memes
sections.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# ==========================================================================
# PARAMETRES
# ==========================================================================
# Jeu d'ajustement du pied dans les rainures du boitier-culasse du C96,
# applique aux largeurs exterieures du pied (semelle et flancs).
tolerance_glissiere = -0.08
# Longueur de la zone basse qui entre dans l'arme.
longueur_pied_c96 = 18.0
# Largeur exterieure totale du corps renforce, hors de l'arme.
largeur_ext_corps_renforce = 18.50
# Epaisseur de la semelle, la meme sur toute la longueur. Une semelle plus
# epaisse sous le seul corps (2,60) est incompatible avec une face d'impression
# plane et un plan d'appui des culots continu : le renfort porte donc sur les
# parois laterales. Les hauteurs ci-dessous sont comptees depuis le dessus du dos.
epaisseur_dos = 1.35
# Pastilles d'ancrage cassables aux quatre coins.
activer_mouse_ears = True
# Rainures de relaxation thermique sous la semelle.
activer_rainures_retrait = True

NOM_FICHIER = "ladestreifen_mauser_c96_heavy_duty"

# --- Longueur (axe X) -----------------------------------------------------
LONGUEUR = 101.50
CAPACITE = 10
LONGUEUR_TRANSITION = 2.50   # rampe entre le pied et le corps (X 18,0 a 20,5)

# --- Enveloppe exterieure -------------------------------------------------
LARGEUR_SEMELLE_PIED = 13.40  # semelle du pied (+ tolerance_glissiere)
LARGEUR_FLANCS_PIED = 11.80   # flancs du pied (+ tolerance_glissiere)
CHANFREIN_PIED = 0.25         # compensation du pied d'elephant, 45 deg, aretes du bas
CHANFREIN_POUCE = 0.80        # chanfrein exterieur du haut du corps, 45 deg

# --- Guidage interne des cartouches (constant de X = 0 a LONGUEUR) --------
HAUTEUR_AILES = 3.40         # ailes au-dessus du dos (hauteur totale 4,75)
ECART_BOURRELET = 10.15      # couloir du culot
HAUTEUR_BOURRELET = 1.40     # hauteur du couloir (Z 1,35 a 2,75)
ECART_LEVRES = 8.65          # ecartement libre entre les levres
ANGLE_PENTE = 45.0           # dessous des levres, mesure depuis l'horizontale
CONGE = 0.45                 # conge interne a la base des parois

# Degagement du haut des levres. Avec des levres verticales jusqu'en haut, les
# 0,5 mm superieurs entrent dans le chanfrein de gorge de l'etui (0,35 mm par
# cote sur la cartouche temoin). Les levres gardent donc une portee verticale
# de cette hauteur, puis s'ouvrent en chanfrein vers le haut (face tournee vers
# le ciel : aucun surplomb). None = levres verticales jusqu'en haut.
PORTEE_LEVRES = 0.40
ANGLE_DEGAGEMENT = 45.0      # mesure depuis la verticale

# --- Retention d'extremite (axe X) ----------------------------------------
ECART_EXTREMITE = 8.15       # ecartement resserre des levres
ANGLE_RAMPE = 30.0           # rampe laterale, mesuree depuis l'axe X
LONGUEUR_RETENTION = 1.20    # longueur totale : chanfrein + palier + rampe
CHANFREIN_ENTREE = 0.50      # chanfrein d'entree, 45 deg

# --- Rainures de relaxation sous la semelle -------------------------------
# Transversales (selon Y), section trapezoidale ouverte sur le plateau, flancs
# a 54,5 deg sur le plateau. Reparties regulierement sur la longueur.
NOMBRE_RAINURES = 3
RAINURE_LARGEUR_BAS = 0.90   # largeur a Z = 0
RAINURE_LARGEUR_HAUT = 0.40  # largeur au fond de la rainure
RAINURE_PROFONDEUR = 0.35

# --- Oreilles d'ancrage (mouse ears) --------------------------------------
# Chaque disque est pose hors d'un coin, sans toucher la piece ; seule une
# patte etroite le relie a la face d'extremite.
OREILLE_DIAMETRE = 16.0
OREILLE_EPAISSEUR = 0.24
PATTE_LARGEUR = 1.50
OREILLE_JEU = 1.00           # distance mini entre un disque et la piece
OREILLES_ECART = 1.00        # distance mini entre les deux disques d'une extremite
PATTE_RETRAIT = 0.30         # distance entre la patte et le chanfrein de pied

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
    demi_corps = largeur_ext_corps_renforce / 2
    demi_semelle = (LARGEUR_SEMELLE_PIED + tolerance_glissiere) / 2
    demi_flancs = (LARGEUR_FLANCS_PIED + tolerance_glissiere) / 2
    if demi_corps < demi_semelle:
        raise ValueError("le corps renforce doit etre plus large que la semelle du pied")
    return {
        "demi_semelle": demi_semelle, "demi_flancs": demi_flancs, "demi_corps": demi_corps,
        "demi_bourrelet": ECART_BOURRELET / 2,
        "demi_levres": demi_levres, "demi_bout": demi_bout,
        "hauteur": epaisseur_dos + HAUTEUR_AILES,
        "z_levres": epaisseur_dos + HAUTEUR_BOURRELET,
        "rampe": rampe, "palier": palier,
        "x_corps": longueur_pied_c96 + LONGUEUR_TRANSITION,
        "angle_transition_semelle": math.degrees(math.atan2(demi_corps - demi_semelle, LONGUEUR_TRANSITION)),
        "angle_transition_flancs": math.degrees(math.atan2(demi_corps - demi_flancs, LONGUEUR_TRANSITION)),
    }


def _interp(x: float, table: list[tuple[float, float]]) -> float:
    """Interpolation lineaire par morceaux dans une table (x, valeur) croissante."""
    for (x0, v0), (x1, v1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            return v0 if x1 == x0 else v0 + (v1 - v0) * (x - x0) / (x1 - x0)
    return table[0][1] if x < table[0][0] else table[-1][1]


def enveloppe(x: float) -> tuple[float, float, float]:
    """(demi-largeur de la semelle, demi-largeur des flancs, chanfrein du haut)
    a l'abscisse x : pied, rampe lineaire, puis corps renforce."""
    c = cotes()
    xs = (0.0, longueur_pied_c96, c["x_corps"], LONGUEUR)
    return (_interp(x, list(zip(xs, (c["demi_semelle"],) * 2 + (c["demi_corps"],) * 2))),
            _interp(x, list(zip(xs, (c["demi_flancs"],) * 2 + (c["demi_corps"],) * 2))),
            _interp(x, list(zip(xs, (0.0, 0.0, CHANFREIN_POUCE, CHANFREIN_POUCE)))))


def contour_exterieur(x: float, z_bas: float = 0.0) -> list[Pt]:
    """Six sommets exterieurs cote +Y, du plateau vers le haut. Certains se
    confondent : les deux du haut dans le pied (pas de chanfrein), les deux de
    l'epaulement dans le corps (flancs au nu de la semelle)."""
    semelle, flancs, haut = enveloppe(x)
    h = cotes()["hauteur"]
    return [(semelle - max(0.0, CHANFREIN_PIED - z_bas), z_bas),
            (semelle, max(CHANFREIN_PIED, z_bas)),
            (semelle, epaisseur_dos), (flancs, epaisseur_dos),
            (flancs, h - haut), (flancs - haut, h)]


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
        if z_deg >= c["hauteur"] or y_haut > c["demi_flancs"] - 0.1:
            raise ValueError("degagement des levres incompatible avec la hauteur des ailes")
        pts += [(w, z_deg), (y_haut, c["hauteur"])]
    return pts


def stations_levres() -> list[tuple[float, float]]:
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


def rainures_x() -> list[float]:
    if not activer_rainures_retrait:
        return []
    return [LONGUEUR * (i + 1) / (NOMBRE_RAINURES + 1) for i in range(NOMBRE_RAINURES)]


def fond_rainure(x: float) -> float:
    """Hauteur du dessous de la semelle a l'abscisse x (0 hors des rainures)."""
    flanc = (RAINURE_LARGEUR_BAS - RAINURE_LARGEUR_HAUT) / 2
    for x0 in rainures_x():
        d = abs(x - x0)
        if d < RAINURE_LARGEUR_BAS / 2:
            return min(RAINURE_PROFONDEUR,
                       (RAINURE_LARGEUR_BAS / 2 - d) * RAINURE_PROFONDEUR / flanc)
    return 0.0


def demi_section(x: float) -> list[Pt]:
    """Demi-section theorique cote +Y a l'abscisse x, du plateau au fond du
    couloir (conge remplace par sa corde). Sert aux controles et a l'apercu."""
    c = cotes()
    pts = contour_exterieur(x, fond_rainure(x))
    pts += reversed(profil_levre(_interp(x, stations_levres())))
    pts += [(c["demi_bourrelet"], epaisseur_dos + CONGE), (c["demi_bourrelet"] - CONGE, epaisseur_dos)]
    return pts


def oreilles() -> list[dict]:
    """Disques et pattes : centre du disque, rectangle de la patte (x0, x1, y0, y1)."""
    if not activer_mouse_ears:
        return []
    r, liste = OREILLE_DIAMETRE / 2, []
    for x_piece, sens in ((0.0, -1), (LONGUEUR, 1)):
        demi = enveloppe(x_piece)[0]
        y_patte = demi - CHANFREIN_PIED - PATTE_RETRAIT - PATTE_LARGEUR / 2
        ey = max(r + OREILLES_ECART / 2, y_patte)
        ex = math.sqrt((r + OREILLE_JEU) ** 2 - max(0.0, ey - demi) ** 2)
        for cote in (1, -1):
            cx = x_piece + sens * ex
            y0, y1 = sorted((cote * (y_patte - PATTE_LARGEUR / 2), cote * (y_patte + PATTE_LARGEUR / 2)))
            liste.append({"centre": (cx, cote * ey), "rayon": r,
                          "patte": (min(cx, x_piece), max(cx, x_piece), y0, y1)})
    return liste


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
    sur le dos, et epaisseurs de paroi : valeurs par cote, negatives en cas
    d'interference."""
    c = cotes()
    profil = profil_levre(c["demi_levres"])
    r_culot, r_gorge = TEMOIN_D_CULOT / 2, TEMOIN_D_GORGE / 2
    pas = [c["z_levres"] + i * 0.001 for i in range(int((c["hauteur"] - c["z_levres"]) / 0.001) + 1)]
    haut = [z for z in pas if z - epaisseur_dos > TEMOIN_EP_BOURRELET + 1e-9]
    jeu_etui = min(demi_ecart_levre(z, profil) - rayon_temoin(z - epaisseur_dos) for z in haut)
    z_contact = c["z_levres"] + (c["demi_bourrelet"] - r_culot) * math.tan(math.radians(ANGLE_PENTE))
    x_butee = (CHANFREIN_ENTREE + c["palier"]
               + math.sqrt(max(0.0, r_gorge**2 - c["demi_bout"] ** 2)))
    return {
        "engagement_levres": r_culot - c["demi_levres"],
        "jeu_lateral_culot": c["demi_bourrelet"] - r_culot,
        "jeu_axial_culot": z_contact - (epaisseur_dos + TEMOIN_EP_BOURRELET),
        "jeu_levres_gorge": c["demi_levres"] - r_gorge,
        "jeu_mini_levres_etui": jeu_etui,
        "paroi_pied_culot": c["demi_flancs"] - c["demi_bourrelet"],
        "paroi_pied_levres": c["demi_flancs"] - c["demi_levres"],
        "paroi_corps_culot": c["demi_corps"] - c["demi_bourrelet"],
        "paroi_corps_levres": c["demi_corps"] - c["demi_levres"],
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
    notes.append(f"transition X {longueur_pied_c96:g} a {c['x_corps']:g} : rampes a "
                 f"{c['angle_transition_semelle']:.1f} deg (semelle) et "
                 f"{c['angle_transition_flancs']:.1f} deg (flancs)")
    notes.append(f"parois du pied : {a['paroi_pied_culot']:.3f} mm au niveau du culot, "
                 f"{a['paroi_pied_levres']:.3f} mm aux levres ; parois du corps : "
                 f"{a['paroi_corps_culot']:.3f} et {a['paroi_corps_levres']:.3f} mm")
    return notes


# ==========================================================================
# SOLIDE CADQUERY
# ==========================================================================
def _sans_doublons(points: list[tuple]) -> list[tuple]:
    """Retire les sommets consecutifs confondus d'un contour ferme."""
    out: list[tuple] = []
    for p in points:
        if not out or math.dist(p, out[-1]) > 1e-9:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) < 1e-9:
        out.pop()
    return out


def enveloppe_solide():
    """Polyedre a faces planes passant par les quatre sections exterieures."""
    import cadquery as cq

    xs = [0.0, longueur_pied_c96, cotes()["x_corps"], LONGUEUR]
    contours = []
    for x in xs:
        droite = contour_exterieur(x)
        contours.append(droite + [(-y, z) for y, z in reversed(droite)])

    def face(points: list[tuple]):
        fil = cq.Wire.makePolygon([cq.Vector(*p) for p in points], close=True)
        return cq.Face.makeFromWires(fil)

    faces, n = [], len(contours[0])
    for k in range(len(xs) - 1):
        for i in range(n):
            j = (i + 1) % n
            pts = _sans_doublons([(xs[k], *contours[k][i]), (xs[k], *contours[k][j]),
                                  (xs[k + 1], *contours[k + 1][j]), (xs[k + 1], *contours[k + 1][i])])
            if len(pts) >= 3:
                faces.append(face(pts))
    for k in (0, -1):
        faces.append(face(_sans_doublons([(xs[k], *p) for p in contours[k]])))
    solide = cq.Solid.makeSolid(cq.Shell.makeShell(faces))
    if solide.Volume() < 0:
        solide = cq.Solid(solide.wrapped.Reversed())
    return solide


def fil_guidage(x: float, w: float):
    """Contour ferme du vide de guidage (couloir + levres) a l'abscisse x,
    prolonge au-dessus de la piece."""
    import cadquery as cq

    c = cotes()
    levre = profil_levre(w)
    dessus = c["hauteur"] + 1.0
    droite = [(c["demi_bourrelet"], epaisseur_dos + CONGE)] + levre + [(levre[-1][0], dessus)]
    k = CONGE * math.sqrt(0.5)
    milieu = (c["demi_bourrelet"] - CONGE + k, epaisseur_dos + CONGE - k)
    depart = (c["demi_bourrelet"] - CONGE, epaisseur_dos)
    wp = cq.Workplane("YZ", origin=(x, 0, 0)).moveTo(*depart).threePointArc(milieu, droite[0])
    for p in droite[1:]:
        wp = wp.lineTo(*p)
    for y, z in reversed(droite[1:]):
        wp = wp.lineTo(-y, z)
    wp = wp.lineTo(-droite[0][0], droite[0][1]).threePointArc((-milieu[0], milieu[1]), (-depart[0], depart[1]))
    return wp.close().val()


def construire():
    """Enveloppe moins guidage, puis rainures retirees et oreilles ajoutees."""
    import cadquery as cq

    st = stations_levres()
    # Le vide de guidage deborde de 0,5 mm a chaque bout pour une coupe nette.
    st = [(-0.5, st[0][1])] + st + [(LONGUEUR + 0.5, st[-1][1])]
    guidage = cq.Solid.makeLoft([fil_guidage(x, w) for x, w in st], ruled=True)
    lame = cq.Workplane("XY").add(enveloppe_solide()).cut(guidage)

    bas, haut, marge = RAINURE_LARGEUR_BAS / 2, RAINURE_LARGEUR_HAUT / 2, 0.1
    for x0 in rainures_x():
        # Trapeze dans le plan XZ, prolonge sous Z = 0, extrude a travers toute la largeur.
        outil = (cq.Workplane("XZ")
                 .polyline([(x0 - bas, -marge), (x0 + bas, -marge), (x0 + bas, 0),
                            (x0 + haut, RAINURE_PROFONDEUR), (x0 - haut, RAINURE_PROFONDEUR),
                            (x0 - bas, 0)])
                 .close().extrude(largeur_ext_corps_renforce, both=True))
        lame = lame.cut(outil)

    recouvrement = 0.3  # la patte entre legerement dans la piece pour une fusion nette
    for o in oreilles():
        (cx, cy), (x0, x1, y0, y1) = o["centre"], o["patte"]
        if x0 < 0:
            x1 += recouvrement
        else:
            x0 -= recouvrement
        disque = cq.Workplane("XY").center(cx, cy).circle(o["rayon"]).extrude(OREILLE_EPAISSEUR)
        patte = (cq.Workplane("XY").center((x0 + x1) / 2, (y0 + y1) / 2)
                 .rect(x1 - x0, y1 - y0).extrude(OREILLE_EPAISSEUR))
        lame = lame.union(disque).union(patte)
    return lame


def exporter(dossier: Path) -> None:
    import cadquery as cq

    for note in controles():
        print(f"  ! {note}")
    modele = construire()
    solide = modele.val()
    if not solide.isValid() or len(modele.solids().vals()) != 1:
        raise RuntimeError("solide invalide ou en plusieurs morceaux")
    boite, a = solide.BoundingBox(), ajustement()
    print(f"  enveloppe {boite.xlen:.2f} x {boite.ylen:.2f} x {boite.zlen:.2f} mm, "
          f"volume {solide.Volume():.1f} mm3")
    print(f"  engagement des levres {a['engagement_levres']:.3f} mm par cote, "
          f"jeu axial du culot {a['jeu_axial_culot']:.3f} mm")
    print(f"  jeu mini levres / etui {a['jeu_mini_levres_etui']:+.3f} mm par cote")
    print(f"  extremites : serrage {a['serrage_extremite']:.3f} mm par cote, depassement "
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
        xs = sorted({x for x, _ in stations_levres()} | {longueur_pied_c96, cotes()["x_corps"]})
        print(json.dumps({"sections": [{"x": x, "demi_section": demi_section(x)} for x in xs],
                          "rainures": rainures_x(), "oreilles": oreilles(),
                          "cotes": cotes(), "ajustement": ajustement()}, indent=1))
        return
    print(f"Ladestreifen Mauser C96 haute resistance, {CAPACITE} coups (pied {longueur_pied_c96:g} mm, "
          f"corps {largeur_ext_corps_renforce:g} mm, dos {epaisseur_dos:g} mm, "
          f"tolerance_glissiere {tolerance_glissiere:+.2f} mm)")
    exporter(args.outdir)


if __name__ == "__main__":
    main()
