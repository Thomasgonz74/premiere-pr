"""Pure-logic tests for resolve_destination and RoutingRuleStore -- no Qt, no
libtorrent. See engine/routing_rules.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore, resolve_destination

DEFAULT = "C:/downloads/default"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


# ----------------------------------------------------------- resolve_destination


def test_no_rules_returns_default():
    assert resolve_destination([], DEFAULT, name="Ubuntu.24.04") == DEFAULT


def test_no_matching_rule_returns_default():
    rules = [RoutingRule(name="r1", pattern="fedora", match_field="name", destination="D:/fedora")]
    assert resolve_destination(rules, DEFAULT, name="Ubuntu.24.04") == DEFAULT


def test_name_match_is_case_insensitive_substring():
    rules = [RoutingRule(name="r1", pattern="UBUNTU", match_field="name", destination="D:/linux")]
    assert resolve_destination(rules, DEFAULT, name="ubuntu.24.04.desktop") == "D:/linux"


def test_first_matching_rule_wins_over_a_later_one_that_would_also_match():
    rules = [
        RoutingRule(name="specific", pattern="ubuntu", match_field="name", destination="D:/ubuntu"),
        RoutingRule(name="generic", pattern="u", match_field="name", destination="D:/generic"),
    ]
    assert resolve_destination(rules, DEFAULT, name="ubuntu.24.04") == "D:/ubuntu"


def test_a_non_matching_earlier_rule_falls_through_to_a_later_matching_one():
    rules = [
        RoutingRule(name="r1", pattern="fedora", match_field="name", destination="D:/fedora"),
        RoutingRule(name="r2", pattern="ubuntu", match_field="name", destination="D:/ubuntu"),
    ]
    assert resolve_destination(rules, DEFAULT, name="ubuntu.24.04") == "D:/ubuntu"


def test_tracker_match_against_any_tracker_in_the_list():
    rules = [RoutingRule(name="r1", pattern="example.com", match_field="tracker", destination="D:/private")]
    trackers = ["http://other.org/announce", "https://tracker.example.com/announce"]
    assert resolve_destination(rules, DEFAULT, trackers=trackers) == "D:/private"


def test_tracker_match_is_case_insensitive():
    rules = [RoutingRule(name="r1", pattern="EXAMPLE.COM", match_field="tracker", destination="D:/private")]
    assert resolve_destination(rules, DEFAULT, trackers=["http://tracker.example.com/announce"]) == "D:/private"


def test_tracker_rule_with_trackers_none_does_not_match():
    """The documented "missing information" case: an RSS item or a fresh
    magnet has no tracker list yet, so a tracker rule must never apply."""
    rules = [RoutingRule(name="r1", pattern="example.com", match_field="tracker", destination="D:/private")]
    assert resolve_destination(rules, DEFAULT, name="anything", trackers=None) == DEFAULT


def test_tracker_rule_with_empty_tracker_list_does_not_match():
    rules = [RoutingRule(name="r1", pattern="example.com", match_field="tracker", destination="D:/private")]
    assert resolve_destination(rules, DEFAULT, trackers=[]) == DEFAULT


def test_name_rule_with_empty_name_does_not_match():
    rules = [RoutingRule(name="r1", pattern="ubuntu", match_field="name", destination="D:/linux")]
    assert resolve_destination(rules, DEFAULT, name="") == DEFAULT


def test_rule_with_empty_pattern_never_matches():
    rules = [RoutingRule(name="r1", pattern="", match_field="name", destination="D:/anything")]
    assert resolve_destination(rules, DEFAULT, name="ubuntu") == DEFAULT


def test_name_rule_does_not_match_against_trackers_and_vice_versa():
    rules = [
        RoutingRule(name="tracker_rule", pattern="ubuntu", match_field="tracker", destination="D:/wrong"),
    ]
    # "ubuntu" is in the torrent name, not any tracker URL -- a "tracker"
    # rule must not match against `name`.
    assert resolve_destination(rules, DEFAULT, name="ubuntu.24.04", trackers=["http://example.com"]) == DEFAULT


# ----------------------------------------------------------------- RoutingRuleStore


def _rule(name: str, destination: str = "D:/dest") -> RoutingRule:
    return RoutingRule(name=name, pattern="x", match_field="name", destination=destination)


def test_save_rule_then_list_round_trips():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))

    rules = store.list_rules()

    assert rules == [_rule("r1")]


def test_save_rule_of_same_name_replaces_it_in_place():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1", "D:/first"))
    store.save_rule(_rule("r0"))
    store.save_rule(_rule("r1", "D:/replaced"))

    names_and_dest = [(r.name, r.destination) for r in store.list_rules()]

    # r1 keeps its original position (index 0), not bumped to the end.
    assert names_and_dest == [("r1", "D:/replaced"), ("r0", "D:/dest")]


def test_delete_removes_the_named_rule():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))
    store.save_rule(_rule("r2"))

    store.delete("r1")

    assert [r.name for r in store.list_rules()] == ["r2"]


def test_reorder_changes_evaluation_order():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))
    store.save_rule(_rule("r2"))
    store.save_rule(_rule("r3"))

    store.reorder(["r3", "r1", "r2"])

    assert [r.name for r in store.list_rules()] == ["r3", "r1", "r2"]


def test_reorder_keeps_a_rule_missing_from_the_new_order_appended_at_the_end():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))
    store.save_rule(_rule("r2"))

    store.reorder(["r2"])  # r1 not mentioned

    assert [r.name for r in store.list_rules()] == ["r2", "r1"]


def test_persists_across_a_fresh_store_instance():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1", "D:/persisted"))

    reloaded = RoutingRuleStore()

    assert [r.destination for r in reloaded.list_rules()] == ["D:/persisted"]


def test_delete_persists_across_a_fresh_store_instance():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))
    store.delete("r1")

    reloaded = RoutingRuleStore()

    assert reloaded.list_rules() == []


def test_reorder_persists_across_a_fresh_store_instance():
    store = RoutingRuleStore()
    store.save_rule(_rule("r1"))
    store.save_rule(_rule("r2"))
    store.reorder(["r2", "r1"])

    reloaded = RoutingRuleStore()

    assert [r.name for r in reloaded.list_rules()] == ["r2", "r1"]


def test_missing_persistence_file_starts_empty():
    store = RoutingRuleStore()
    assert store.list_rules() == []


def test_corrupt_persistence_file_does_not_crash_startup():
    from torrent2000.config.paths import get_routing_rules_path

    get_routing_rules_path().write_text("not valid json {{{", encoding="utf-8")

    store = RoutingRuleStore()  # must not raise

    assert store.list_rules() == []


def test_persistence_file_with_wrong_top_level_shape_does_not_crash_startup():
    from torrent2000.config.paths import get_routing_rules_path

    get_routing_rules_path().write_text('{"not": "a list"}', encoding="utf-8")

    store = RoutingRuleStore()  # must not raise

    assert store.list_rules() == []


def test_persistence_file_with_malformed_entry_skips_it_without_crashing():
    import json

    from torrent2000.config.paths import get_routing_rules_path

    get_routing_rules_path().write_text(json.dumps([{"name": "broken"}]), encoding="utf-8")

    store = RoutingRuleStore()  # missing required fields -- must not raise

    assert store.list_rules() == []
