"""Simple "if the name/tracker contains X, use folder Y" auto-routing rules.

Today AddTorrentTab, RssFeedService, and WatchFolderService each pass a
single destination folder straight through to
SessionManager.add_torrent_from_file/add_torrent_from_magnet, chosen by the
caller (a manual field, the feed's default_download_dir, the watch folder's
default_download_dir) with nothing inspecting the torrent's name or tracker
to redirect it elsewhere. RoutingRuleStore/resolve_destination below let the
user define an ordered list of substring-match rules that each of those three
callers consults to resolve a destination BEFORE calling into
session_manager -- session_manager itself stays completely unaware this
exists, it always just receives whatever save_path its caller decided on.

Persistence follows the same tmp-file + os.replace() pattern as
engine/torrent_categories.py and engine/settings_profiles.py: tolerant of a
missing or corrupt file (starts empty rather than crashing startup), atomic
write via a .tmp sibling.
"""

import json
import os
from dataclasses import asdict, dataclass

from torrent2000.config.paths import get_routing_rules_path


@dataclass
class RoutingRule:
    name: str  # rule name, for display/management -- not matched against anything itself
    pattern: str  # substring to search for, case-insensitive
    match_field: str  # "name" | "tracker"
    destination: str  # absolute destination folder


class RoutingRuleStore:
    """Persists an ordered list of RoutingRule entries to disk as JSON. Order
    matters: rules are evaluated top-to-bottom by resolve_destination() and
    the first match wins, so the order here IS the user's priority list --
    see reorder()."""

    def __init__(self) -> None:
        self._rules: list[RoutingRule] = []
        self._load()

    def list_rules(self) -> list[RoutingRule]:
        return list(self._rules)

    def save_rule(self, rule: RoutingRule) -> None:
        """Adds `rule`, or replaces the existing rule of the same name in
        place (same position), preserving its priority slot rather than
        bumping an edited rule to the end of the list."""
        for i, existing in enumerate(self._rules):
            if existing.name == rule.name:
                self._rules[i] = rule
                self._save()
                return
        self._rules.append(rule)
        self._save()

    def delete(self, name: str) -> None:
        self._rules = [r for r in self._rules if r.name != name]
        self._save()

    def reorder(self, names: list[str]) -> None:
        """Re-orders rules to match `names`' order (a full list of every
        rule's name, in the desired new order -- e.g. from a Monter/
        Descendre button swap in the UI). Any existing rule whose name isn't
        present in `names` is kept, appended after the reordered ones, rather
        than silently dropped."""
        by_name = {r.name: r for r in self._rules}
        reordered = [by_name[n] for n in names if n in by_name]
        missing = [r for r in self._rules if r.name not in names]
        self._rules = reordered + missing
        self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_routing_rules_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = [asdict(r) for r in self._rules]
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_routing_rules_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, list):
            return  # malformed top-level shape -- start empty rather than crash on startup
        for entry in data:
            try:
                self._rules.append(RoutingRule(**entry))
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup


def resolve_destination(
    rules: list[RoutingRule],
    default_destination: str,
    name: str = "",
    trackers: list[str] | None = None,
) -> str:
    """Evaluates `rules` in order and returns the destination of the first
    one that matches, or `default_destination` unchanged if none does (or if
    the information a rule would need is missing -- e.g. a "tracker" rule
    when `trackers` is None, which every caller that can't know a torrent's
    trackers yet, like an unfetched RSS item or a fresh magnet, passes).

    A rule only ever matches if its own pattern is non-empty (an
    accidentally-saved blank pattern must never blanket-match everything)
    and, for match_field == "tracker", against at least one entry of
    `trackers` -- an empty list is treated the same as no match, same as
    None."""
    for rule in rules:
        if not rule.pattern:
            continue
        needle = rule.pattern.lower()
        if rule.match_field == "name":
            if name and needle in name.lower():
                return rule.destination
        elif rule.match_field == "tracker":
            if trackers and any(needle in tracker.lower() for tracker in trackers):
                return rule.destination
    return default_destination
