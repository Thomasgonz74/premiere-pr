"""Theme identifiers referenced outside the UI layer (engine download-gating,
stats leveling multipliers) as well as inside it. Kept as a standalone leaf
module with zero dependencies so engine/ and stats/ code can key behavior off
the active theme without importing anything from ui/.
"""

MACOS_THEME_ID = "macos_modern"
CCCP_THEME_ID = "cccp_soviet"
