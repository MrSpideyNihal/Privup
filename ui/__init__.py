"""PrivUp local web UI.

A thin presentation layer over ``core.main.run``. Run it with ``python -m ui``.
"""

from ui.server import analyze, build_server, guess_driver, serve

__all__ = ["analyze", "build_server", "guess_driver", "serve"]
