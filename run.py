import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from torrent2000.app import main

if __name__ == "__main__":
    main()
