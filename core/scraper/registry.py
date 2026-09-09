"""Driver registry.

Drivers self-register with the ``@register_driver`` decorator. Lookup is by
name, so ``core/main.py`` never imports a concrete driver and never grows an
if-else chain as drivers are added.

Third-party packages can register without touching this repo at all, by
declaring a ``privup.drivers`` entry point:

	[project.entry-points."privup.drivers"]
	play_store = "my_package.play_store_driver"

``load_plugin_drivers()`` imports those modules, which runs their decorators.
"""

from __future__ import annotations

from importlib import metadata
from typing import Iterator, Type, TypeVar

from core.scraper.base import Driver

__all__ = [
	"register_driver",
	"get_driver",
	"get_driver_class",
	"available_drivers",
	"describe_drivers",
	"load_plugin_drivers",
	"UnknownDriverError",
]

ENTRY_POINT_GROUP = "privup.drivers"

_REGISTRY: dict[str, Type[Driver]] = {}

D = TypeVar("D", bound=Type[Driver])


class UnknownDriverError(KeyError):
	"""Asked for a driver name that nothing registered."""

	def __init__(self, name: str) -> None:
		known = ", ".join(available_drivers()) or "none"
		super().__init__(f"unknown driver {name!r}; registered drivers: {known}")
		self.name = name


def register_driver(cls: D) -> D:
	"""Class decorator that adds a driver to the registry.

	Re-registering the same class is a no-op so that a module imported twice
	under different paths does not explode. Registering a *different* class
	under a taken name is an error, because silently shadowing a driver would
	change what the pipeline analyzes without anyone noticing.
	"""
	name = getattr(cls, "name", "")
	if not name:
		raise ValueError(f"{cls.__name__} must set a non-empty 'name' to register")

	existing = _REGISTRY.get(name)
	if existing is not None and existing is not cls:
		raise ValueError(
			f"driver name {name!r} is already registered to {existing.__name__}"
		)

	_REGISTRY[name] = cls
	return cls


def get_driver_class(name: str) -> Type[Driver]:
	"""Return the registered driver class for ``name``."""
	try:
		return _REGISTRY[name]
	except KeyError:
		raise UnknownDriverError(name) from None


def get_driver(name: str) -> Driver:
	"""Instantiate the registered driver for ``name``."""
	return get_driver_class(name)()


def available_drivers() -> list[str]:
	"""Registered driver names, sorted."""
	return sorted(_REGISTRY)


def describe_drivers() -> Iterator[tuple[str, str]]:
	"""Yield ``(name, description)`` for every registered driver."""
	for name in available_drivers():
		yield name, _REGISTRY[name].description


def load_plugin_drivers() -> list[str]:
	"""Import every module advertised under the ``privup.drivers`` group.

	Returns the names of entry points that loaded. A broken third-party
	plugin must not take the pipeline down, so import failures are collected
	and skipped rather than raised.
	"""
	loaded: list[str] = []
	try:
		entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
	except Exception:
		return loaded

	for entry_point in entry_points:
		try:
			entry_point.load()
		except Exception:
			continue
		loaded.append(entry_point.name)
	return loaded
