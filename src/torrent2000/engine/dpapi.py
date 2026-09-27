"""Windows DPAPI (Data Protection API) wrapper for secrets Settings persists
to config.json at rest -- proxy.password and remote_access_token. Ties
encryption to the current Windows user account (no separate passphrase to
manage/lose); a blob decrypts only for that same user on that same machine.

Defense in depth, not a silver bullet: anything else already running as the
same Windows user could call CryptUnprotectData itself. It DOES protect
against config.json being copied off this machine (support ticket, cloud
sync, USB) or read by a different Windows account on a shared PC.

Confined to this one small module so the rest of the app only ever handles
plaintext -- see Settings.save()/load() for the only two call sites.
"""

import base64
import ctypes
from ctypes import wintypes

_PREFIX = "dpapi:"  # marks a value as an encrypted blob, vs. plaintext -- see unprotect()


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    # The buffer object is returned alongside the blob and must be kept
    # alive by the caller for as long as the blob is in use -- ctypes does
    # not keep it alive on its own via the POINTER cast.
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _read_and_free(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(plaintext: str) -> str:
    """Encrypts plaintext for the current Windows user; returns a
    "dpapi:"-prefixed base64 string safe to embed in JSON. Empty string
    passes through unchanged -- nothing to protect."""
    if not plaintext:
        return plaintext
    data_in, _keepalive = _to_blob(plaintext.encode("utf-8"))
    data_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    return _PREFIX + base64.b64encode(_read_and_free(data_out)).decode("ascii")


def unprotect(value: str) -> str:
    """Decrypts a value produced by protect(). A value without the "dpapi:"
    prefix is assumed to already be plaintext -- a config.json saved before
    this feature existed -- and is returned unchanged; the next save() call
    then protects it, migrating it transparently with no schema version
    bump needed. A blob that fails to decrypt (different machine/user,
    corrupted) fails safe to "" rather than raising and blocking
    Settings.load() entirely."""
    if not value.startswith(_PREFIX):
        return value
    try:
        encrypted = base64.b64decode(value[len(_PREFIX):])
    except (ValueError, TypeError):
        return ""
    data_in, _keepalive = _to_blob(encrypted)
    data_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    )
    if not ok:
        return ""
    try:
        return _read_and_free(data_out).decode("utf-8")
    except UnicodeDecodeError:
        return ""
