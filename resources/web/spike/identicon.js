// Per-torrent visual fingerprint: a tiny deterministic pattern derived from
// info_hash, so torrents are distinguishable at a glance in the Downloads
// list (catalogue "idées non implémentées" / Visualisations avancées).
// GitHub-identicon style -- 5x5 grid, mirrored left/right so it reads as a
// blob rather than noise. The pattern and the hue come from the hash: they
// identify the TORRENT, so they are the same in every theme. Only the colour
// recipe comes from theme tokens (see style.css, "Optional theme tokens"):
// the saturation/lightness of both colours, or a fixed monochrome pair.
// Known bug: the LCG below overflows 2^53 before `>>> 0`, its low bit is
// then always 0 and almost no hash draws a block -- today only the hue tells
// torrents apart, and a monochrome pair makes every identicon the same plain
// square. Math.imul fixes it but changes every identicon: left for a later lot.
// No bridge call needed (record.infoHash is already present client-side on
// every row).

function identiconHash(infoHash) {
  // ponytail: simple 32-bit rolling hash, not cryptographic -- a stable
  // deterministic fingerprint is all this needs, not collision resistance.
  let h = 0;
  const str = infoHash || "";
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0;
  }
  return h;
}

// Resolved once per theme/mode: a canvas fill cannot take var().
let _identiconRecipe = null;
function identiconRecipe() {
  if (!_identiconRecipe) {
    const cs = getComputedStyle(document.documentElement);
    const token = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
    _identiconRecipe = {
      paperSL: token("--identicon-paper-sl", "60% 92%"),
      inkSL: token("--identicon-ink-sl", "65% 42%"),
      paper: token("--identicon-paper", ""),
      ink: token("--identicon-ink", ""),
    };
  }
  return _identiconRecipe;
}

// Drawn once per row (downloads.js), then again on every theme or mode change.
document.addEventListener("t2k-themechange", () => {
  _identiconRecipe = null;
  for (const canvas of document.querySelectorAll("canvas.identicon")) {
    drawIdenticon(canvas, canvas._identiconHash);
  }
});

function drawIdenticon(canvas, infoHash) {
  canvas._identiconHash = infoHash;
  const size = canvas.width; // square canvas; CSS never rescales it
  const cols = 5;
  const cell = size / cols;
  const seed = identiconHash(infoHash);

  const hue = seed % 360;
  const recipe = identiconRecipe();
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = recipe.paper || `hsl(${hue} ${recipe.paperSL})`; // background tint
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = recipe.ink || `hsl(${hue} ${recipe.inkSL})`; // foreground blocks

  // Walk the left half + center column bit-by-bit (LCG stream seeded from
  // the hash), mirroring each block into the right half so the pattern is
  // symmetric -- readable as one shape instead of random static.
  let bits = seed;
  for (let col = 0; col < 3; col++) {
    for (let row = 0; row < cols; row++) {
      bits = (bits * 1103515245 + 12345) >>> 0; // ponytail: LCG, fine for a visual pattern (but see the known bug above)
      if ((bits & 1) === 0) continue;
      ctx.fillRect(col * cell, row * cell, cell, cell);
      if (col < 2) ctx.fillRect((cols - 1 - col) * cell, row * cell, cell, cell);
    }
  }
}
