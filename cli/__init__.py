"""PrivUp command line interface.

A thin wrapper over ``core.main.run``. It parses arguments, formats output and
picks an exit status. It contains no pipeline logic, and adding any here would
mean the CLI and the UI could disagree about what a policy says.
"""

from cli.main import build_parser, main

__all__ = ["build_parser", "main"]
