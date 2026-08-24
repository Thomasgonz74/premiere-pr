#!/usr/bin/env python3
"""Lint dev : repere les chaines FR visibles (>40 caracteres) dans
resources/web/spike/*.js -- candidates a verifier pour troncature dans un
conteneur a largeur fixe (le spike web n'a aucun systeme i18n : tout le
texte francais est en dur dans les .js).

Pas un vrai parseur JS : regex sur les patrons deja observes dans le code
(textContent=, innerText=, title=, aria-label=, alertModal(...), y compris
les template strings). Outil de confort dev, pas un gate CI -- l'exit code
n'est non-zero que si une chaine NOUVELLE (absente de EXCLUDED ci-dessous)
depasse le seuil.

Usage : python scripts/lint_long_strings.py
"""

import re
import sys
from pathlib import Path

THRESHOLD = 40
REPO_ROOT = Path(__file__).resolve().parent.parent
SPIKE_DIR = REPO_ROOT / "resources" / "web" / "spike"

# Chaines deja connues/acceptees (baseline generee lors de l'ecriture de ce
# script, 2026-08-24, en scannant l'etat actuel de resources/web/spike/ --
# les 20 candidates trouvees a ce moment-la ont ete relues et jugees ok
# telles quelles). Ne font pas echouer le lint. Ajouter ici toute nouvelle
# chaine volontairement longue et deja verifiee visuellement (pas de
# troncature genante dans son conteneur).
EXCLUDED = {
    "Avant de commencer, faites un tour dans l'onglet Profil : vous y trouverez les réglages de confidentialité et de réseau (proxy, chiffrement, découverte réseau) qui déterminent ce que vos pairs peuvent voir de votre activité.",
    "Choisissez d'abord un fichier ou un dossier source.",
    "${record.numPeers} (${record.numSeeds} seeds)",
    "Aucun torrent actif — ajoutez-en un depuis l'onglet Ajouter pour le voir apparaître ici en direct.",
    'Tracker actuel : ${record.currentTracker || "—"}',
    "Le lien magnet n'est pas encore disponible pour ce torrent : les métadonnées n'ont pas encore été reçues. Réessayez une fois le torrent analysé.",
    "Aucune information de fichiers disponible pour le moment (métadonnées non reçues, ou torrent introuvable).",
    "Décocher l'unique fichier exclura le torrent entier.",
    "Voulez-vous vraiment retirer cet élément ?",
    "Tous les téléchargements sont terminés. Extinction dans ${_shutdownCountdownRemaining} s.",
    "Une nouvelle version (${version}) est disponible.",
    "La mise à jour a été téléchargée et vérifiée.",
    "Aucune règle de classement pour l'instant.",
    "Définissez des règles « si le nom ou le tracker contient X, alors dossier Y » pour orienter ",
    "Le nom, le motif et le dossier de destination sont obligatoires.",
    "Enregistrez le proxy, le chiffrement, les notifications, les limites de débit et la restriction ",
    "Contrôle le volume de l'hymne joué en fond sonore par le thème CCCP.",
    "Analyser les fichiers téléchargés avec Windows Defender",
    "Téléchargé : ${formatSize(snap.totalDownloaded)}  —  Envoyé : ${formatSize(snap.totalUploaded)}",
    "Aucun torrent partagé — ajoutez-en un ci-dessus pour le voir apparaître ici en direct.",
}

# Un literal JS quote/quote (simple, double ou template), avec échappement.
_STRING = r"(?P<q>[`\"'])(?P<str>(?:\\.|(?!(?P=q))[\s\S])*)(?P=q)"
ASSIGN_RE = re.compile(r"\b(?:textContent|innerText|title|aria-label)\s*=\s*" + _STRING)
STRING_RE = re.compile(_STRING)
ALERTMODAL_RE = re.compile(r"alertModal\(([\s\S]*?)\)\s*;")


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def find_candidates(text):
    """Retourne une liste de (ligne, contenu) pour chaque literal trouve,
    sans filtrage de longueur."""
    found = []
    for m in ASSIGN_RE.finditer(text):
        found.append((_line_of(text, m.start()), m.group("str")))
    for block in ALERTMODAL_RE.finditer(text):
        base = block.start(1)
        for sm in STRING_RE.finditer(block.group(1)):
            found.append((_line_of(text, base + sm.start()), sm.group("str")))
    found.sort(key=lambda item: item[0])
    return found


def main():
    # Windows consoles aren't always UTF-8; avoid crashing on accented output.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not SPIKE_DIR.is_dir():
        print(f"Dossier introuvable : {SPIKE_DIR}", file=sys.stderr)
        return 2

    total = 0
    new_ones = []
    for path in sorted(SPIKE_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for line, content in find_candidates(text):
            if len(content) <= THRESHOLD:
                continue
            total += 1
            preview = content.replace("\n", "\\n")
            if len(preview) > 70:
                preview = preview[:70] + "..."
            known = content in EXCLUDED
            tag = "connu" if known else "NOUVEAU"
            rel = path.relative_to(REPO_ROOT)
            print(f"[{tag}] {rel}:{line}  ({len(content)} car.)  {preview}")
            if not known:
                new_ones.append((rel, line))

    print(f"\n{total} chaine(s) candidate(s) au total, {len(new_ones)} nouvelle(s) a verifier.")
    return 1 if new_ones else 0


if __name__ == "__main__":
    sys.exit(main())
