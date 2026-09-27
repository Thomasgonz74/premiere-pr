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
// data-i18n-placeholder/-title/-aria-label for those attributes) instead of
// being rebuilt on every language change: rebuilding would drop any
// in-progress user input and re-register event listeners. Dynamically
// rendered content (list rows, dialogs) isn't tagged -- it already calls
// t() fresh on its own next render (next poll tick, next add/remove, next
// dialog open), so it naturally picks up a language change without any
// extra wiring here.

let __catalog = {};

function setCatalog(catalog) {
  __catalog = catalog || {};
  applyStaticTranslations();
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
}
