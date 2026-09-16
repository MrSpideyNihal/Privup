"""Allow ``python -m cli`` in a checkout without installing anything."""

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.main import main

raise SystemExit(main())
