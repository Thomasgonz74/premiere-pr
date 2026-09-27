"""Freezes the PieceMapBridge wire format decoded by piece_map_dialog.js:
two strings with one char per piece -- have "1"/"0", availability a peer
count capped at "9". Changing it means changing the JS decoder too."""

from torrent2000.ui.web.bridge_piece_map import PieceMapBridge


class _FakeSessionManager:
    def __init__(self, data):
        self._data = data

    def get_piece_availability(self, info_hash):
        return self._data


def test_piece_map_is_encoded_as_two_digit_strings():
    bridge = PieceMapBridge(
        _FakeSessionManager({"num_pieces": 5, "have": [True, False, False, True, False], "availability": [0, 2, 3, 12, 300]})
    )

    assert bridge.getPieceAvailability("abc") == {"numPieces": 5, "have": "10010", "availability": "02399"}


def test_piece_map_without_metadata_or_seeding_encodes_empty_strings():
    # get_piece_availability's not-ready shape, and libtorrent's empty
    # availability list for a seed.
    bridge = PieceMapBridge(_FakeSessionManager({"num_pieces": 0, "have": [], "availability": []}))

    assert bridge.getPieceAvailability("abc") == {"numPieces": 0, "have": "", "availability": ""}
