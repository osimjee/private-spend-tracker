#!/usr/bin/env python3
"""Run the tracker straight from a download, without installing anything:

    python3 scripts/spendscan.py "/path/to/my_statements" --open

(After `pip install .` you can run the same thing with just:  spendscan "/path/to/my_statements")
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from private_spend_tracker.spendscan import main  # noqa: E402

if __name__ == "__main__":
    main()
