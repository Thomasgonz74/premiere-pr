// Thin catalog-lookup layer for the web UI (see i18n/translator.py for the
// Python-side equivalent). Loaded first, before every other script, so t()
// is callable from any *BuildPage()/render function at parse time.
//
// The Python side already resolves the French-fallback rule (see
// bridge_i18n.py::getCatalog -> translator.effective_catalog()), so this is
// a plain flat-dict lookup, not a second implementation of that rule.
//
// Static DOM -- built once, either directly in index.html or once inside a
// *BuildPage() function -- is tagged with data-i18n-key (and
// data-i18n-placeholder/-title/-aria-label/-tooltip for those attributes) instead of
// being rebuilt on every language change: rebuilding would drop any
// in-progress user input and re-register event listeners. Runtime-built
// text that is a plain key (an empty-list note, a row's button) is tagged
// the same way. Text built from more than a key (a row's state and rates, a
// value read from the bridge) is rebuilt by its page on "catalogchange":
// an idle torrent's row, say, gets no next render to pick the language up.
// Dialogs call t() afresh each time they open.

let __catalog = {};

function setCatalog(catalog) {
  __catalog = catalog || {};
  applyStaticTranslations();
  document.dispatchEvent(new Event("catalogchange"));
}

function t(key, params) {
  let text = __catalog[key];
  if (text === undefined) return key;
  if (params) {
    text = text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? params[name] : match));
  }
  return text;
}

function applyStaticTranslations() {
  document.querySelectorAll("[data-i18n-key]").forEach((el) => {
    el.textContent = t(el.dataset.i18nKey);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-i18n-tooltip]").forEach((el) => {
    el.setAttribute("data-tooltip", t(el.dataset.i18nTooltip));
  });
}
