"""Driver interface, registry, and the raw_text driver."""

from __future__ import annotations

import pytest

from core.models import DriverResult
from core.scraper import (
	Driver,
	DriverError,
	UnknownDriverError,
	available_drivers,
	describe_drivers,
	get_driver,
)
from core.scraper import registry as registry_module
from core.scraper.registry import register_driver


@pytest.fixture
def clean_registry():
	"""Restore the registry so a test's throwaway driver does not leak."""
	saved = dict(registry_module._REGISTRY)
	yield
	registry_module._REGISTRY.clear()
	registry_module._REGISTRY.update(saved)


class TestRegistry:
	def test_built_in_drivers_are_registered_on_import(self):
		assert "raw_text" in available_drivers()
		assert "url" in available_drivers()

	def test_describe_returns_a_line_per_driver(self):
		described = dict(describe_drivers())
		assert described["raw_text"]
		assert described["url"]

	def test_unknown_driver_names_the_ones_that_exist(self):
		with pytest.raises(UnknownDriverError) as caught:
			get_driver("nope")
		assert "raw_text" in str(caught.value)

	def test_a_third_party_driver_plugs_in_with_no_core_changes(self, clean_registry):
		"""The pluggability claim, tested rather than asserted."""

		@register_driver
		class PdfDriver(Driver):
			name = "pdf_test"
			description = "third-party style driver"

			def fetch(self, target: str) -> DriverResult:
				return self.build_result("text from a pdf", origin=target)

		assert "pdf_test" in available_drivers()
		result = get_driver("pdf_test").fetch("loan.pdf")
		assert result.driver == "pdf_test"
		assert result.origin == "loan.pdf"

	def test_name_collision_is_loud(self, clean_registry):
		"""Shadowing a driver would change what gets analyzed silently."""
		with pytest.raises(ValueError, match="already registered"):

			@register_driver
			class Clashing(Driver):
				name = "raw_text"

				def fetch(self, target: str) -> DriverResult:
					return self.build_result("x", origin=target)

	def test_registering_the_same_class_twice_is_harmless(self, clean_registry):
		@register_driver
		class Idempotent(Driver):
			name = "idempotent_test"

			def fetch(self, target: str) -> DriverResult:
				return self.build_result("x", origin=target)

		register_driver(Idempotent)
		assert available_drivers().count("idempotent_test") == 1

	def test_a_driver_without_a_name_cannot_register(self, clean_registry):
		with pytest.raises(ValueError, match="non-empty 'name'"):

			@register_driver
			class Nameless(Driver):
				def fetch(self, target: str) -> DriverResult:
					return self.build_result("x", origin=target)

	def test_plugin_loading_survives_no_plugins_installed(self):
		assert isinstance(registry_module.load_plugin_drivers(), list)


class TestRawTextDriver:
	@pytest.fixture
	def driver(self):
		return get_driver("raw_text")

	def test_passes_text_through_unchanged(self, driver):
		text = "We retain your data indefinitely."
		result = driver.fetch(text)
		assert result.raw_text == text
		assert result.driver == "raw_text"
		assert result.origin == "raw_text"

	def test_detects_html(self, driver):
		result = driver.fetch("<html><body><p>We share data.</p></body></html>")
		assert result.content_type == "text/html"

	def test_does_not_mistake_prose_for_html(self, driver):
		"""'<18 years of age' is a real phrase in real policies."""
		result = driver.fetch("You must be 18. Users <18 cannot register on this service.")
		assert result.content_type == "text/plain"

	def test_empty_input_raises_rather_than_returning_nothing(self, driver):
		"""Returning an empty result would let the scorer report Allow."""
		with pytest.raises(DriverError, match="empty"):
			driver.fetch("")

	def test_whitespace_only_input_raises(self, driver):
		with pytest.raises(DriverError):
			driver.fetch("   \n\t  ")

	def test_non_string_input_raises(self, driver):
		with pytest.raises(DriverError, match="string"):
			driver.fetch(None)  # type: ignore[arg-type]

	def test_records_length_in_metadata(self, driver):
		assert driver.fetch("hello there").metadata["length"] == 11
