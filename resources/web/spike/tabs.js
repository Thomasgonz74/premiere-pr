// Tab switcher for the spike shell -- plain show/hide, no routing needed at
// this scale (3 tabs).
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`page-${btn.dataset.tab}`).classList.add("active");
  });
});

function switchToTab(name) {
  document.querySelector(`.tab-btn[data-tab="${name}"]`)?.click();
}
