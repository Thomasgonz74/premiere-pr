"""Round-trip tests for the Windows DPAPI wrapper backing Settings' at-rest
encryption of proxy.password/remote_access_token (see engine/dpapi.py)."""

from torrent2000.engine import dpapi


def test_protect_unprotect_round_trip():
    blob = dpapi.protect("hunter2")
    assert blob.startswith("dpapi:")
    assert blob != "hunter2"
    assert dpapi.unprotect(blob) == "hunter2"


def test_unicode_round_trip():
    blob = dpapi.protect("mot de passe éàü")
    assert dpapi.unprotect(blob) == "mot de passe éàü"


def test_empty_string_passes_through_unprotected():
    assert dpapi.protect("") == ""
    assert dpapi.unprotect("") == ""


def test_preexisting_plaintext_value_passes_through_unchanged():
    assert dpapi.unprotect("already-plaintext") == "already-plaintext"


def test_corrupted_blob_fails_safe_to_empty_string():
    assert dpapi.unprotect("dpapi:not-valid-base64-!!!") == ""
    assert dpapi.unprotect("dpapi:AAAAAAAA") == ""
