"""Shared secret redaction for any Settings dict about to leave the live
config file -- an export, or a timestamped backup snapshot. Mirrors which
fields settings_history.py already excludes from its own diff log
(`proxy` and `remote_access_token`), so all three places agree on what
counts as sensitive.
"""

def redact_settings_dict(data: dict) -> dict:
    """Mutates and returns `data` (as produced by dataclasses.asdict(settings)
    or json.loads() of a config file) with proxy.password and
    remote_access_token zeroed out. Safe to call on a dict missing either
    key (nothing to redact yet)."""
    proxy = data.get("proxy")
    if isinstance(proxy, dict) and "password" in proxy:
        proxy["password"] = ""
    if "remote_access_token" in data:
        data["remote_access_token"] = ""
    return data
