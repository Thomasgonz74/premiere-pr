// Live peer list for one torrent. Mirrors PeerListDialog/PeerListTable:
// same 5 columns, same 2s poll while the dialog is open, poll stops on
// close instead of tying its lifetime to the downloads list's own polling.

const PEER_LIST_HEADERS = ["IP", "Client", "Progression", "↓ Vitesse", "↑ Vitesse"];

// Opt-in (Settings.peer_reputation_enabled, see engine/peer_reputation.py) --
// column only gets added when bridge.peerList.isReputationEnabled() says so.
const PEER_REPUTATION_LABELS = { good: "Bonne", neutral: "Neutre", bad: "Mauvaise" };

function _peerListRenderRows(list, peers, reputationScores) {
  list.replaceChildren();

  if (peers.length === 0) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucun pair connecté.";
    list.appendChild(note);
    return;
  }

  peers.forEach((peer) => {
    const row = document.createElement("div");
    row.className = "row";

    const ipEl = document.createElement("div");
    ipEl.className = "row-name";
    ipEl.textContent = peer.ip;
    row.appendChild(ipEl);

    const clientEl = document.createElement("div");
    clientEl.textContent = peer.client;
    row.appendChild(clientEl);

    const progressEl = document.createElement("div");
    progressEl.className = "row-rate";
    progressEl.textContent = `${Math.round(peer.progress * 100)}%`;
    row.appendChild(progressEl);

    const downEl = document.createElement("div");
    downEl.className = "row-rate";
    downEl.textContent = formatRate(peer.downSpeed);
    row.appendChild(downEl);

    const upEl = document.createElement("div");
    upEl.className = "row-rate";
    upEl.textContent = formatRate(peer.upSpeed);
    row.appendChild(upEl);

    if (reputationScores) {
      const score = reputationScores[peer.ip] || "neutral";
      const repEl = document.createElement("div");
      repEl.className = `reputation-badge reputation-${score}`;
      repEl.textContent = PEER_REPUTATION_LABELS[score] || PEER_REPUTATION_LABELS.neutral;
      row.appendChild(repEl);
    }

    list.appendChild(row);
  });
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
      window.bridge.peerList.getPeers(infoHash, (peers) => {
        if (!reputationEnabled || peers.length === 0) {
          _peerListRenderRows(list, peers, null);
          return;
        }
        window.bridge.peerList.getReputationScores(
          peers.map((p) => p.ip),
          (scores) => _peerListRenderRows(list, peers, scores)
        );
      });
    };
    refresh();
    const timer = setInterval(refresh, 2000);

    openModal(`Pairs — ${torrentName}`, contentEl, () => clearInterval(timer));
  });
}
