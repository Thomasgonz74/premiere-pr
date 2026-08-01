"""Pure-logic tests for RSS 2.0 XML parsing and keyword matching -- no Qt,
no network. See engine/rss_feed_service.py.
"""

from torrent2000.engine.rss_feed_service import matches_keyword, parse_rss_items

_SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Tracker</title>
    <item>
      <title>Ubuntu.24.04.Desktop.amd64</title>
      <link>https://example.com/torrents/ubuntu.torrent</link>
      <guid>urn:example:1</guid>
    </item>
    <item>
      <title>Debian.12.netinst</title>
      <link>magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01&amp;dn=debian</link>
      <guid>urn:example:2</guid>
    </item>
    <item>
      <title>NoGuidItem</title>
      <link>https://example.com/torrents/noguid.torrent</link>
    </item>
    <item>
      <title>EnclosureItem</title>
      <link>https://example.com/page/enclosure-item</link>
      <enclosure url="https://example.com/torrents/enclosure.torrent" type="application/x-bittorrent" />
      <guid>urn:example:4</guid>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_items_extracts_title_link_guid():
    items = parse_rss_items(_SAMPLE_FEED)
    assert len(items) == 4

    first = items[0]
    assert first["title"] == "Ubuntu.24.04.Desktop.amd64"
    assert first["link"] == "https://example.com/torrents/ubuntu.torrent"
    assert first["guid"] == "urn:example:1"


def test_parse_rss_items_keeps_magnet_links_untouched():
    items = parse_rss_items(_SAMPLE_FEED)
    magnet_item = items[1]
    assert magnet_item["link"].startswith("magnet:?xt=urn:btih:")


def test_parse_rss_items_falls_back_to_link_when_guid_missing():
    items = parse_rss_items(_SAMPLE_FEED)
    no_guid_item = items[2]
    assert no_guid_item["guid"] == no_guid_item["link"] == "https://example.com/torrents/noguid.torrent"


def test_parse_rss_items_prefers_enclosure_url_over_link():
    items = parse_rss_items(_SAMPLE_FEED)
    enclosure_item = items[3]
    assert enclosure_item["link"] == "https://example.com/torrents/enclosure.torrent"
    assert enclosure_item["guid"] == "urn:example:4"


def test_parse_rss_items_returns_empty_list_for_malformed_xml():
    assert parse_rss_items(b"not xml at all <<<") == []


def test_parse_rss_items_returns_empty_list_when_no_items():
    empty_feed = b"<rss version='2.0'><channel><title>Empty</title></channel></rss>"
    assert parse_rss_items(empty_feed) == []


def test_matches_keyword_empty_keyword_matches_everything():
    assert matches_keyword("Anything.Goes.Here", "") is True


def test_matches_keyword_case_insensitive_substring():
    assert matches_keyword("Ubuntu.24.04.Desktop.amd64", "ubuntu") is True
    assert matches_keyword("Ubuntu.24.04.Desktop.amd64", "UBUNTU") is True
    assert matches_keyword("Ubuntu.24.04.Desktop.amd64", "fedora") is False
