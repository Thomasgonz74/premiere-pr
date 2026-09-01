// CCCP theme's propaganda side panel -- port of ui/widgets/propaganda_panel.py.
// Cycles through 18 tongue-in-cheek messages (shuffled order, no immediate
// repeat of the same shuffle pass), each paired with one of 8 hand-drawn
// icons rendered once from the real Python paint routines (see
// scratchpad/generate_propaganda_icons.py) and recolored live via CSS
// mask-image + background-color, exactly like the native _PropagandaIcon's
// single-color repaint but without re-deriving the bezier/polygon math in
// JS. Message text is hardcoded French, matching the rest of this web spike
// (no i18n layer exists here yet -- see plan notes).

const PROPAGANDA_MESSAGE_INTERVAL_MS = 17000;

const PROPAGANDA_MESSAGE_SPECS = [
  ["star", "Camarade, votre contribution au partage collectif a été inscrite au tableau d'honneur du Politburo. La Patrie numérique vous remercie."],
  ["hammer_sickle", "Le marteau frappe les fichiers verrouillés, la faucille moissonne les graines partagées. Ensemble, camarade, ils forgent votre ratio."],
  ["gear", "Chaque rouage de ce kolkhoze numérique tourne grâce à votre bande passante. Ne grippez pas la machine collective, camarade."],
  ["sun_rays", "Le levant du partage universel se lève sur le kolkhoze numérique. Un jour nouveau, un octet nouveau, camarade."],
  ["wheat", "La moisson de graines dépasse cette semaine les objectifs du plan quinquennal. Qui a dit que « seed » n'était pas un mot de la terre ?"],
  ["rocket", "Votre bande passante atteint l'orbite plus vite que le premier Spoutnik. Le cosmos du pair-à-pair vous salue, camarade."],
  ["factory", "L'usine numérique du kolkhoze tourne à plein régime : vous, camarade, en êtes le fier ouvrier de l'octet."],
  ["fist", "Levez le poing, camarade : chaque fichier partagé est un coup porté à l'exploitation... du disque dur du voisin qui ne partage jamais."],
  ["star", "Un camarade qui télécharge sans jamais partager n'est qu'une sangsue bourgeoise déguisée en pair. Le Politburo n'est pas dupe."],
  ["hammer_sickle", "Sous l'emblème du Parti, on ne dit pas « peer-to-peer » : on dit « camarade à camarade ». C'est plus long, mais tellement plus loyal."],
  ["gear", "Le Comité Central salue votre bande passante, généreusement redistribuée aux rouages du peuple plutôt qu'accaparée comme un vulgaire capitaliste."],
  ["sun_rays", "Chaque connexion pair-à-pair rapproche le prolétariat de l'aube radieuse... du ratio positif."],
  ["wheat", "Sous ce régime, celui qui ne sème pas de graines ne récolte pas de bande passante. C'est la loi du kolkhoze, camarade, pas la mienne."],
  ["rocket", "Votre altruisme numérique sera cité en exemple au prochain congrès du Parti, quelque part entre l'orbite et le Kremlin."],
  ["factory", "Le glorieux plan quinquennal de la bande passante avance grâce à votre sacrifice héroïque, camarade machiniste de l'octet."],
  ["fist", "Un octet caché est un octet volé au peuple. Serrez le poing, pas le fichier, camarade."],
  ["star", "Ici, on ne dit pas « télécharger ». On dit « attendre dignement en servant le peuple », comme dans toute bonne file d'attente soviétique."],
  ["hammer_sickle", "Camarade, votre seedbox sera commémorée sur la Place Rouge numérique, juste à côté du mausolée du tracker."],
];

let _propagandaOrder = [];
let _propagandaPosition = -1;
let _propagandaTimer = null;

function _shuffledIndices(n) {
  const arr = Array.from({ length: n }, (_, i) => i);
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function _showNextPropagandaMessage() {
  _propagandaPosition += 1;
  if (_propagandaPosition >= _propagandaOrder.length) {
    _propagandaPosition = 0;
    _propagandaOrder = _shuffledIndices(PROPAGANDA_MESSAGE_SPECS.length);
  }
  const [kind, message] = PROPAGANDA_MESSAGE_SPECS[_propagandaOrder[_propagandaPosition]];
  const iconEl = document.getElementById("propagandaIcon");
  iconEl.style.maskImage = `url("assets/propaganda/${kind}.png")`;
  iconEl.style.webkitMaskImage = `url("assets/propaganda/${kind}.png")`;
  document.getElementById("propagandaMessage").textContent = message;
}

function startPropagandaPanel() {
  document.getElementById("cccpPropagandaPanel").hidden = false;
  _propagandaOrder = _shuffledIndices(PROPAGANDA_MESSAGE_SPECS.length);
  _propagandaPosition = -1;
  _showNextPropagandaMessage();
  if (_propagandaTimer) clearInterval(_propagandaTimer);
  _propagandaTimer = setInterval(_showNextPropagandaMessage, PROPAGANDA_MESSAGE_INTERVAL_MS);
}

function stopPropagandaPanel() {
  document.getElementById("cccpPropagandaPanel").hidden = true;
  if (_propagandaTimer) {
    clearInterval(_propagandaTimer);
    _propagandaTimer = null;
  }
}
