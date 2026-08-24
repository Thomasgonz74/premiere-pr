// Per-torrent visual fingerprint: a tiny deterministic pattern derived from
// info_hash, so torrents are distinguishable at a glance in the Downloads
// list (catalogue "idées non implémentées" / Visualisations avancées).
// GitHub-identicon style -- 5x5 grid, mirrored left/right so it reads as a
// blob rather than noise. Colors come from the hash itself, never from
// theme tokens: the point is to identify the TORRENT, not to match the
// active charter, so it must look identical across all 34 themes.
// Pure function of infoHash -- no bridge call needed (record.infoHash is
// already present client-side on every row).

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

function drawIdenticon(canvas, infoHash) {
  const size = canvas.width; // square canvas; CSS never rescales it
  const cols = 5;
  const cell = size / cols;
  const seed = identiconHash(infoHash);

  const hue = seed % 360;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = `hsl(${hue}, 60%, 92%)`; // background tint
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = `hsl(${hue}, 65%, 42%)`; // foreground blocks

  // Walk the left half + center column bit-by-bit (LCG stream seeded from
  // the hash), mirroring each block into the right half so the pattern is
  // symmetric -- readable as one shape instead of random static.
  let bits = seed;
  for (let col = 0; col < 3; col++) {
    for (let row = 0; row < cols; row++) {
      bits = (bits * 1103515245 + 12345) >>> 0; // ponytail: LCG, fine for a visual pattern
      if ((bits & 1) === 0) continue;
      ctx.fillRect(col * cell, row * cell, cell, cell);
      if (col < 2) ctx.fillRect((cols - 1 - col) * cell, row * cell, cell, cell);
    }
  }
}
