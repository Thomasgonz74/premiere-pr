#!/usr/bin/env python3
"""Cartouches de manipulation (snap caps) monolithiques - generateur parametrique.

Calibres : 9x19 mm Parabellum et 8x22 mm Nambu.
Piece inerte d'un seul tenant (douille + ogive), sans amorce : le logement
d'amorce recoit un tampon silicone retenu par une gorge en contre-depouille.

Usage :
    pip install cadquery
    python snap_caps.py                     # exporte STEP + STL dans ./output
    python snap_caps.py --outdir build --stl-tol 0.001 --ang-tol 0.03
    python snap_caps.py --profile-json      # profil 2D seul (sans CadQuery)

Conventions : unites en mm, axe de revolution = Z, culot en Z = 0.
Le profil 2D est decrit dans le demi-plan (r, z) par des segments de droite et
des arcs exacts ; c'est ce meme profil que l'apercu Three.js fait tourner.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

Pt = tuple[float, float]  # (r, z)


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Pocket:
    """Logement d'amorce Small Pistol, gorge d'ancrage et event (communs)."""

    d: float = 4.45            # diametre du logement
    depth: float = 3.30        # profondeur
    chamfer: float = 0.30      # chanfrein d'entree, 45 deg
    undercut_z: float = 2.00   # profondeur du debut de la gorge d'ancrage
    undercut_dr: float = 0.35  # sur-rayon de la gorge (diametre local 5.15)
    undercut_h: float = 0.80   # hauteur de la gorge
    vent_d: float = 1.00       # diametre de l'event


@dataclass(frozen=True)
class Caliber:
    name: str
    slug: str
    rim_d: float               # diametre du culot
    rim_t: float               # epaisseur du bourrelet
    groove_d: float            # diametre fond de gorge d'extraction
    groove_w: float            # largeur du fond de gorge (partie cylindrique)
    body_d: float              # diametre du corps a sa base (haut du chanfrein de gorge)
    case_len: float            # longueur de douille (plan des levres)
    mouth_d: float             # diametre aux levres
    bullet_d: float            # diametre de l'ogive a sa base
    oal: float                 # longueur totale
    nose_r: float              # rayon de la pointe arrondie
    stations: tuple[tuple[float, float], ...] = ()  # (z, diametre) intermediaires
    fillet_r: float = 0.0      # conge sur les stations intermediaires
    rim_chamfer: float = 0.30  # chanfrein inferieur du culot, 45 deg
    groove_angle: float = 35.0  # chanfrein superieur de gorge, mesure depuis l'axe
    bullet_cyl: float = 0.0    # portee cylindrique de l'ogive avant la courbure
    spec_lip_step: float = 0.15  # feuillure demandee au cahier des charges
    pocket: Pocket = field(default_factory=Pocket)


CAL_9X19 = Caliber(
    name="9x19 mm Parabellum", slug="snapcap_9x19",
    rim_d=9.96, rim_t=1.27, groove_d=8.40, groove_w=1.45,
    body_d=9.93, case_len=19.15, mouth_d=9.65,
    bullet_d=9.02, oal=29.30, nose_r=1.8,
)

CAL_8X22 = Caliber(
    name="8x22 mm Nambu", slug="snapcap_8x22_nambu",
    rim_d=10.50, rim_t=1.15, groove_d=8.90, groove_w=1.40,
    body_d=10.30, case_len=22.00, mouth_d=8.80,
    bullet_d=8.18, oal=31.60, nose_r=1.6,
    stations=((16.00, 9.95), (17.80, 8.85)), fillet_r=0.4,
)

CALIBERS = (CAL_9X19, CAL_8X22)


# --------------------------------------------------------------------------
# Geometrie 2D pure (aucune dependance)
# --------------------------------------------------------------------------
def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def _mul(a: Pt, k: float) -> Pt:
    return (a[0] * k, a[1] * k)


def _unit(a: Pt) -> Pt:
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n)


def _arc(start: Pt, end: Pt, center: Pt, radius: float) -> dict:
    """Arc < 180 deg de start a end ; le point milieu sert a threePointArc."""
    bis = _unit(_add(_sub(start, center), _sub(end, center)))
    return {"t": "A", "p": end, "mid": _add(center, _mul(bis, radius)),
            "c": center, "r": radius, "from": start}


def _fillet(prev: Pt, corner: Pt, nxt: Pt, radius: float) -> tuple[Pt, Pt, Pt]:
    """Conge tangent aux deux segments : (point d'entree, point de sortie, centre)."""
    v1, v2 = _unit(_sub(prev, corner)), _unit(_sub(nxt, corner))
    half = math.acos(max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1]))) / 2
    setback = radius / math.tan(half)
    bis = _unit(_add(v1, v2))
    return (_add(corner, _mul(v1, setback)), _add(corner, _mul(v2, setback)),
            _add(corner, _mul(bis, radius / math.sin(half))))


def derived(c: Caliber) -> dict:
    """Cotes calculees a partir des parametres (utiles au controle)."""
    p = c.pocket
    rg, rb, rbul = c.groove_d / 2, c.body_d / 2, c.bullet_d / 2
    z_groove_top = c.rim_t + c.groove_w
    z_body = z_groove_top + (rb - rg) / math.tan(math.radians(c.groove_angle))
    # Ogive tangente emoussee par une sphere : rayon rho tel que l'arc parte
    # tangent au cylindre en z0 et se raccorde tangent a la pointe de rayon rn.
    z0 = c.case_len + c.bullet_cyl
    length = c.oal - z0
    rn = c.nose_r
    if not 0 < rn < rbul:
        raise ValueError(f"{c.name}: rayon de pointe hors plage")
    rho = (rbul**2 + (length - rn) ** 2 - rn**2) / (2 * (rbul - rn))
    oc: Pt = (rbul - rho, z0)
    nc: Pt = (0.0, c.oal - rn)
    tangent = _add(oc, _mul(_unit(_sub(nc, oc)), rho))
    # Event : droite inclinee du fond du logement au milieu du fond de gorge.
    a: Pt = (p.d / 2 - p.vent_d / 2, p.depth)
    b: Pt = (rg, c.rim_t + c.groove_w / 2)
    tilt = math.atan2(a[1] - b[1], b[0] - a[0])  # par rapport au plan radial
    half_print = p.vent_d / 2 / math.cos(tilt)
    return {
        "z_groove_top": z_groove_top, "z_body": z_body,
        "lip_step": c.mouth_d / 2 - rbul,
        "ogive_r": rho, "ogive_c": oc, "nose_c": nc, "ogive_tangent": tangent,
        "ogive_z0": z0,
        "vent_a": a, "vent_b": b, "vent_tilt_deg": math.degrees(tilt),
        "vent_exit_z": (b[1] - half_print, b[1] + half_print),
        "undercut_z": (p.undercut_z, p.undercut_z + p.undercut_h),
        "undercut_d": p.d + 2 * p.undercut_dr,
    }


def profile(c: Caliber) -> tuple[Pt, list[dict]]:
    """Profil ferme (demi-coupe) : point de depart + segments 'L' / 'A'."""
    p, d = c.pocket, derived(c)
    rp, rr, rg = p.d / 2, c.rim_d / 2, c.groove_d / 2
    rbul = c.bullet_d / 2
    start: Pt = (rp + p.chamfer, 0.0)
    segs: list[dict] = []

    def line(pt: Pt) -> None:
        segs.append({"t": "L", "p": pt})

    # Culot et gorge d'extraction
    line((rr - c.rim_chamfer, 0.0))
    line((rr, c.rim_chamfer))
    line((rr, c.rim_t))
    line((rg, c.rim_t))
    line((rg, d["z_groove_top"]))
    # Corps : base -> stations (conges) -> levres
    body: list[Pt] = [(c.body_d / 2, d["z_body"])]
    body += [(dia / 2, z) for z, dia in c.stations]
    body.append((c.mouth_d / 2, c.case_len))
    line(body[0])
    for i in range(1, len(body) - 1):
        if c.fillet_r > 0:
            t1, t2, ctr = _fillet(body[i - 1], body[i], body[i + 1], c.fillet_r)
            line(t1)
            segs.append(_arc(t1, t2, ctr, c.fillet_r))
        else:
            line(body[i])
    line(body[-1])
    # Feuillure nette puis ogive
    line((rbul, c.case_len))
    if c.bullet_cyl > 0:
        line((rbul, d["ogive_z0"]))
    segs.append(_arc((rbul, d["ogive_z0"]), d["ogive_tangent"], d["ogive_c"], d["ogive_r"]))
    segs.append(_arc(d["ogive_tangent"], (0.0, c.oal), d["nose_c"], c.nose_r))
    # Retour par l'axe, logement d'amorce et gorge d'ancrage
    z_u0, z_u1 = d["undercut_z"]
    ru = rp + p.undercut_dr
    for pt in [(0.0, p.depth), (rp, p.depth), (rp, z_u1), (ru, z_u1),
               (ru, z_u0), (rp, z_u0), (rp, p.chamfer)]:
        line(pt)
    return start, segs


def check(c: Caliber) -> list[str]:
    """Controles de coherence ; renvoie les avertissements."""
    d, p, notes = derived(c), c.pocket, []
    lo, hi = d["vent_exit_z"]
    if lo <= c.rim_t or hi >= d["z_groove_top"]:
        raise ValueError(f"{c.name}: l'event deborde du fond de gorge "
                         f"({lo:.2f}..{hi:.2f} mm)")
    wall = c.groove_d / 2 - d["undercut_d"] / 2
    if wall < 1.0:
        notes.append(f"voile gorge d'ancrage / gorge d'extraction = {wall:.2f} mm")
    if abs(d["lip_step"] - c.spec_lip_step) > 1e-6:
        notes.append(
            f"feuillure = {d['lip_step']:.3f} mm au rayon (levres {c.mouth_d:.2f}"
            f" -> ogive {c.bullet_d:.2f}) ; les {c.spec_lip_step:.2f} mm demandes"
            " sont incompatibles avec ces deux diametres, les diametres priment")
    if d["undercut_z"][1] > p.depth - 0.3:
        notes.append("gorge d'ancrage trop proche du fond du logement")
    return notes


# --------------------------------------------------------------------------
# Solide CadQuery
# --------------------------------------------------------------------------
def build(c: Caliber):
    import cadquery as cq

    start, segs = profile(c)
    wp = cq.Workplane("XZ").moveTo(*start)
    for s in segs:
        wp = wp.lineTo(*s["p"]) if s["t"] == "L" else wp.threePointArc(s["mid"], s["p"])
    body = wp.close().revolve(360, (0, 0, 0), (0, 1, 0))

    # Event : percage incline dans le plan XZ (cote +X). L'outil est borne par
    # le plan du fond du logement (pas d'entaille au-dessus) et par le cylindre
    # du fond de gorge (il ne touche ni le bourrelet ni le chanfrein).
    p, d = c.pocket, derived(c)
    a, b = d["vent_a"], d["vent_b"]
    u = _unit(_sub(b, a))
    s0 = _sub(a, _mul(u, 3.0))
    length = math.hypot(*_sub(b, a)) + 5.0
    tool = cq.Solid.makeCylinder(p.vent_d / 2, length,
                                 cq.Vector(s0[0], 0, s0[1]), cq.Vector(u[0], 0, u[1]))
    bound = cq.Solid.makeCylinder(c.groove_d / 2 + 0.02, p.depth,
                                  cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
    return body.cut(tool.intersect(bound))


def export(c: Caliber, outdir: Path, stl_tol: float, ang_tol: float) -> None:
    import cadquery as cq

    for note in check(c):
        print(f"  ! {note}")
    model = build(c)
    solid = model.val()
    if not solid.isValid():
        raise RuntimeError(f"{c.name}: solide invalide")
    bb = solid.BoundingBox()
    d = derived(c)
    print(f"  ogive tangente R = {d['ogive_r']:.3f} mm, "
          f"event incline de {d['vent_tilt_deg']:.1f} deg")
    print(f"  enveloppe d {bb.xlen:.3f} x L {bb.zlen:.3f} mm, "
          f"volume {solid.Volume():.1f} mm3")
    outdir.mkdir(parents=True, exist_ok=True)
    step, stl = outdir / f"{c.slug}.step", outdir / f"{c.slug}.stl"
    cq.exporters.export(model, str(step))
    cq.exporters.export(model, str(stl), tolerance=stl_tol, angularTolerance=ang_tol)
    print(f"  -> {step}\n  -> {stl}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", type=Path, default=Path(__file__).parent / "output")
    ap.add_argument("--stl-tol", type=float, default=0.002,
                    help="deviation lineaire max du maillage STL, mm (defaut 0.002)")
    ap.add_argument("--ang-tol", type=float, default=0.05,
                    help="deviation angulaire max du maillage STL, rad (defaut 0.05)")
    ap.add_argument("--profile-json", action="store_true",
                    help="affiche le profil 2D et les cotes derivees, sans export")
    args = ap.parse_args()

    if args.profile_json:
        out = {}
        for c in CALIBERS:
            start, segs = profile(c)
            out[c.slug] = {"start": start, "segments": segs, "derived": derived(c)}
        print(json.dumps(out, indent=1))
        return
    for c in CALIBERS:
        print(c.name)
        export(c, args.outdir, args.stl_tol, args.ang_tol)


if __name__ == "__main__":
    main()
