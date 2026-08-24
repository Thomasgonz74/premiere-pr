// Pedagogical "?" tooltips for technical terms (sequential download,
// protocol encryption, DHT/LSD discovery, seeds vs peers, share ratio, ...).
// Deliberately NOT the native title="" attribute: unstyled by the active
// theme and inconsistent across browsers -- same reasoning as the titlebar
// buttons using aria-label instead of title. Mirrors contextmenu.js's
// pattern of a single floating element positioned via getBoundingClientRect
// and clamped to the viewport.

// Builds a `<span class="info-hint" tabindex="0" data-tooltip="...">?</span>`
// for JS-built UI (see profile_network.js). Static markup in index.html uses
// the same class/attributes written directly in the HTML.
function makeInfoHint(text) {
  const span = document.createElement("span");
  span.className = "info-hint";
  span.tabIndex = 0;
  span.setAttribute("data-tooltip", text);
  span.textContent = "?";
  return span;
}

let infoTooltipBubble = null;

function showInfoTooltip(hint) {
  const text = hint.getAttribute("data-tooltip");
  if (!text) return;
  if (!infoTooltipBubble) {
    infoTooltipBubble = document.createElement("div");
    infoTooltipBubble.className = "info-tooltip-bubble";
    document.body.appendChild(infoTooltipBubble);
  }
  infoTooltipBubble.textContent = text;
  infoTooltipBubble.style.display = "block";

  const hintRect = hint.getBoundingClientRect();
  const bubbleRect = infoTooltipBubble.getBoundingClientRect();
  let top = hintRect.top - bubbleRect.height - 6;
  if (top < 4) top = hintRect.bottom + 6; // no room above -- flip below
  let left = hintRect.left + hintRect.width / 2 - bubbleRect.width / 2;
  left = Math.max(4, Math.min(left, window.innerWidth - bubbleRect.width - 4));
  infoTooltipBubble.style.top = `${top}px`;
  infoTooltipBubble.style.left = `${left}px`;
}

function hideInfoTooltip() {
  if (infoTooltipBubble) infoTooltipBubble.style.display = "none";
}

document.addEventListener("mouseover", (event) => {
  const hint = event.target.closest(".info-hint");
  if (hint) showInfoTooltip(hint);
});
document.addEventListener("mouseout", (event) => {
  if (event.target.closest(".info-hint")) hideInfoTooltip();
});
document.addEventListener("focusin", (event) => {
  const hint = event.target.closest(".info-hint");
  if (hint) showInfoTooltip(hint);
});
document.addEventListener("focusout", (event) => {
  if (event.target.closest(".info-hint")) hideInfoTooltip();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideInfoTooltip();
});

// Several hints sit inside a <label> (native or wrapping a checkbox/for=id
// target) so their host row toggles on click. The hint itself isn't a
// control -- swallow the click so it doesn't also flip the checkbox.
document.addEventListener("click", (event) => {
  if (event.target.closest(".info-hint")) event.preventDefault();
});
