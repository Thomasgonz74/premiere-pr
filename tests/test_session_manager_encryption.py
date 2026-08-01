"""Pure-logic tests for the encryption-mode -> libtorrent settings mapping.

See engine/session_manager.py's _encryption_settings_fragment -- the exact
enc_policy/enc_level integer values are pinned against this installed
libtorrent build (2.0.13.0): enc_policy.forced=0, enabled=1, disabled=2;
enc_level.plaintext=1, rc4=2, both=3.
"""

from torrent2000.engine.session_manager import _encryption_settings_fragment


def test_forced_mode_refuses_plaintext():
    fragment = _encryption_settings_fragment("forced")
    assert fragment == {
        "out_enc_policy": 0,
        "in_enc_policy": 0,
        "allowed_enc_level": 2,
    }


def test_enabled_mode_is_libtorrent_default():
    fragment = _encryption_settings_fragment("enabled")
    assert fragment == {
        "out_enc_policy": 1,
        "in_enc_policy": 1,
        "allowed_enc_level": 3,
    }


def test_disabled_mode():
    fragment = _encryption_settings_fragment("disabled")
    assert fragment == {
        "out_enc_policy": 2,
        "in_enc_policy": 2,
        "allowed_enc_level": 3,
    }


def test_unknown_mode_falls_back_to_enabled():
    assert _encryption_settings_fragment("bogus") == _encryption_settings_fragment("enabled")
