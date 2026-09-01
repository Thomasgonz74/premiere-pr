// Live peer list for one torrent. Mirrors PeerListDialog/PeerListTable:
// same 5 columns, same 2s poll while the dialog is open, poll stops on
// close instead of tying its lifetime to the downloads list's own polling.

const PEER_LIST_HEADERS = ["IP", "Client", "Progression", "↓ Vitesse", "↑ Vitesse"];

// Opt-in (Settings.peer_reputation_enabled, see engine/peer_reputation.py) --
// column only gets added when bridge.peerList.isReputationEnabled() says so.
const PEER_REPUTATION_LABELS = { good: "Bonne", neutral: "Neutre", bad: "Mauvaise" };

function _peerListBuildRow(withReputation) {
  const el = document.createElement("div");
  el.className = "row";

  const ip = document.createElement("div");
  ip.className = "row-name";
  el.appendChild(ip);

  const client = document.createElement("div");
  el.appendChild(client);

  const progress = document.createElement("div");
  progress.className = "row-rate";
  el.appendChild(progress);

  const down = document.createElement("div");
  down.className = "row-rate";
  el.appendChild(down);

  const up = document.createElement("div");
  up.className = "row-rate";
  el.appendChild(up);

  const rep = withReputation ? document.createElement("div") : null;
  if (rep) el.appendChild(rep);

  return { el, ip, client, progress, down, up, rep };
}

function _peerListRenderRows(list, peers, reputationEnabled) {
  if (peers.length === 0) {
    list.replaceChildren();
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucun pair connecté.";
    list.appendChild(note);
    list._peerRows = null;
    return;
  }

  // Reuses existing row nodes positionally (same order as `peers`, so the
  // rendered result matches a full rebuild) instead of destroying and
  // recreating every row on each 2s poll -- rows are only created the first
  // time or removed if the peer count shrinks.
  let rows = list._peerRows;
  if (!rows) {
    list.replaceChildren();
    rows = [];
    list._peerRows = rows;
  }

  peers.forEach((peer, i) => {
    let row = rows[i];
    if (!row) {
      row = _peerListBuildRow(reputationEnabled);
      rows.push(row);
      list.appendChild(row.el);
    }
    row.ip.textContent = peer.ip;
    row.client.textContent = peer.client;
    row.progress.textContent = `${Math.round(peer.progress * 100)}%`;
    row.down.textContent = formatRate(peer.downSpeed);
    row.up.textContent = formatRate(peer.upSpeed);
    if (reputationEnabled && row.rep) {
      const score = peer.reputation || "neutral";
      row.rep.className = `reputation-badge reputation-${score}`;
      row.rep.textContent = PEER_REPUTATION_LABELS[score] || PEER_REPUTATION_LABELS.neutral;
    }
  });

  while (rows.length > peers.length) {
    list.removeChild(rows.pop().el);
  }
}

function openPeerListDialog(infoHash, torrentName) {
  const contentEl = document.createElement("div");

  const header = document.createElement("div");
  header.className = "row";
  header.style.fontWeight = "bold";
  contentEl.appendChild(header);

  const list = document.createElement("div");
  list.className = "listbox";
  contentEl.appendChild(list);

  window.bridge.peerList.isReputationEnabled((reputationEnabled) => {
    const headers = reputationEnabled ? [...PEER_LIST_HEADERS, "Réputation"] : PEER_LIST_HEADERS;
    headers.forEach((text) => {
      const cell = document.createElement("div");
      cell.textContent = text;
      header.appendChild(cell);
    });

    const refresh = () => {
      // Reputation (when enabled) now comes back directly on each peer
      // object from getPeers() -- a separate getReputationScores()
      // round-trip is no longer needed.
      window.bridge.peerList.getPeers(infoHash, (peers) => {
        _peerListRenderRows(list, peers, reputationEnabled);
      });
    };
    refresh();
    const timer = setInterval(refresh, 2000);

    openModal(`Pairs — ${torrentName}`, contentEl, () => clearInterval(timer));
  });
}
