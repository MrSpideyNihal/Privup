"""Scraper components: pluggable drivers that turn a target into text.

Importing this package registers the built-in drivers and any third-party
drivers advertised under the ``privup.drivers`` entry-point group.
"""

from core.scraper.base import Driver, DriverError
from core.scraper.registry import (
	UnknownDriverError,
	available_drivers,
	describe_drivers,
	get_driver,
	get_driver_class,
	load_plugin_drivers,
	register_driver,
)

# Importing these modules runs their @register_driver decorators.
from core.scraper import raw_text_driver as _raw_text_driver  # noqa: F401
from core.scraper import url_driver as _url_driver  # noqa: F401

load_plugin_drivers()

__all__ = [
	"Driver",
	"DriverError",
	"UnknownDriverError",
	"available_drivers",
	"describe_drivers",
	"get_driver",
	"get_driver_class",
	"load_plugin_drivers",
	"register_driver",
]
