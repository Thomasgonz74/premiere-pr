// Right-click context menu, shared by Downloads and Share rows. Each item is
// { label, onClick } or { separator: true }.

function showContextMenu(x, y, items) {
  closeContextMenu();

  const menu = document.createElement("div");
  menu.className = "context-menu";
  menu.id = "activeContextMenu";

  items.forEach((item) => {
    if (item.separator) {
      const sep = document.createElement("div");
      sep.className = "context-menu-separator";
      menu.appendChild(sep);
      return;
    }
    const entry = document.createElement("div");
    entry.className = "context-menu-item";
    entry.textContent = item.label; // safe: DOM property assignment
    entry.addEventListener("click", () => {
      closeContextMenu();
      item.onClick();
    });
    menu.appendChild(entry);
  });

  document.body.appendChild(menu);

  // Clamp inside the viewport -- a click near the window edge shouldn't
  // spawn a menu that's partly cut off.
  const maxX = window.innerWidth - menu.offsetWidth - 4;
  const maxY = window.innerHeight - menu.offsetHeight - 4;
  menu.style.left = `${Math.max(0, Math.min(x, maxX))}px`;
  menu.style.top = `${Math.max(0, Math.min(y, maxY))}px`;
}

function closeContextMenu() {
  document.getElementById("activeContextMenu")?.remove();
}

document.addEventListener("click", closeContextMenu);
document.addEventListener("contextmenu", (event) => {
  if (!event.target.closest(".context-menu")) closeContextMenu();
});
