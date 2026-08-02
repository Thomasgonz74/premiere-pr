import json

import pytest

from torrent2000.i18n import translator


@pytest.fixture(autouse=True)
def _reset_language():
    # Every test in this module mutates global translator state -- clear
    # the lazily-loaded catalog cache before AND after each test (not just
    # after) so a previous test's teardown re-populating "fr" can't leak a
    # warm cache entry into a test that expects a truly empty one.
    translator._catalogs.clear()
    yield
    translator._catalogs.clear()
    translator.set_language(translator.DEFAULT_LANGUAGE)


def test_default_language_is_french():
    assert translator.DEFAULT_LANGUAGE == "fr"


def test_set_language_rejects_unknown_code_and_falls_back_to_default():
    translator.set_language("not-a-real-language")
    assert translator.current_language() == translator.DEFAULT_LANGUAGE


def test_set_language_accepts_none():
    translator.set_language(None)
    assert translator.current_language() == translator.DEFAULT_LANGUAGE


def test_tr_returns_the_key_itself_when_entirely_unknown():
    translator.set_language("fr")
    assert translator.tr("this.key.does.not.exist.anywhere") == "this.key.does.not.exist.anywhere"


def test_tr_resolves_a_real_french_key():
    translator.set_language("fr")
    assert translator.tr("common.cancel") == "Annuler"


def test_tr_formats_placeholders():
    translator.set_language("fr")
    assert translator.tr("profile_tab.level_value", level=7) == "Niveau 7"


def test_tr_falls_back_to_french_when_target_language_catalog_is_missing_the_key(tmp_path, monkeypatch):
    # Simulate a language catalog that exists but is incomplete (e.g. a
    # string added after that language's file was last regenerated).
    monkeypatch.setattr(translator, "resource_path", lambda rel: tmp_path if rel == "resources/i18n" else tmp_path)
    (tmp_path / "xx.json").write_text(json.dumps({"common.cancel": "XX-CANCEL"}), encoding="utf-8")
    (tmp_path / "fr.json").write_text(json.dumps({"common.cancel": "Annuler", "common.add": "Ajouter"}), encoding="utf-8")

    translator._VALID_LANGUAGE_CODES.add("xx")
    try:
        translator.set_language("xx")
        assert translator.tr("common.cancel") == "XX-CANCEL"  # present in xx -> used directly
        assert translator.tr("common.add") == "Ajouter"  # missing in xx -> falls back to fr
    finally:
        translator._VALID_LANGUAGE_CODES.discard("xx")


def test_tr_survives_a_missing_catalog_file_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(translator, "resource_path", lambda rel: tmp_path)
    translator._VALID_LANGUAGE_CODES.add("yy")
    try:
        translator.set_language("yy")
        # No yy.json and no fr.json exist in this empty tmp_path -- must
        # degrade to the raw key rather than raising.
        assert translator.tr("common.cancel") == "common.cancel"
    finally:
        translator._VALID_LANGUAGE_CODES.discard("yy")


def test_all_eleven_languages_are_declared():
    codes = {code for _, code in translator.LANGUAGE_LABELS}
    assert codes == {"fr", "en", "es", "de", "pt", "it", "zh", "ja", "ko", "pl", "ru"}


def test_language_labels_are_shown_in_their_own_language_not_translated():
    labels = dict(translator.LANGUAGE_LABELS)
    # Autonyms: every language names itself, regardless of current UI
    # language -- this is what makes them meaningful in a menu shown
    # before the user has necessarily picked a language they can read.
    assert ("Français", "fr") in translator.LANGUAGE_LABELS
    assert ("English", "en") in translator.LANGUAGE_LABELS
    assert ("Русский", "ru") in translator.LANGUAGE_LABELS
