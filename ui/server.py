"""A local web UI for PrivUp.

Standard library only, no build step, no accounts, no storage. It serves three
static files and two JSON endpoints, and every endpoint is a thin call into
``core.main.run``. There is no pipeline logic here; if there were, the UI and
the CLI could disagree about what a policy says.

Local means local. The server binds to the loopback interface, refuses
requests whose Host header is not loopback, and sends no CORS headers, so a
page on the open internet cannot quietly drive it. The only outbound traffic
this process ever makes is whatever a driver makes inside ``fetch``.

	python -m ui
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from core.main import run
from core.models import Decision
from core.scraper import DriverError, UnknownDriverError
from core.tags import UnknownTagSetError, describe_tag_sets

__all__ = ["build_server", "serve", "guess_driver", "analyze"]

STATIC_DIR = Path(__file__).parent / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420

# Anything longer than this is not something a person pasted into a box.
MAX_BODY_BYTES = 2 * 1024 * 1024

_CONTENT_TYPES = {
	".html": "text/html; charset=utf-8",
	".css": "text/css; charset=utf-8",
	".js": "text/javascript; charset=utf-8",
	".svg": "image/svg+xml",
}

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

# A single line with no spaces that looks like a host or an http URL.
_URL_LIKE = re.compile(
	r"^(?:https?://\S+|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?:[/?#]\S*)?)$",
	re.IGNORECASE,
)


def guess_driver(target: str) -> str:
	"""Pick a driver from what the user typed.

	One line that looks like a link is a link. Everything else is text. Which
	one was chosen is reported back and shown in the result, so the guess is
	never silent.
	"""
	stripped = target.strip()
	if "\n" in stripped or " " in stripped:
		return "raw_text"
	return "url" if _URL_LIKE.match(stripped) else "raw_text"


def analyze(target: str, tag_set: str, driver: str | None = None) -> dict:
	"""Run the pipeline and shape the result for the browser."""
	chosen = driver or guess_driver(target)
	verdict = run(chosen, target, tag_set)

	payload = verdict.to_dict()
	payload["driver"] = chosen
	payload["decision_label"] = {
		Decision.ALLOW: "Allow",
		Decision.WARNING: "Warning",
		Decision.DENY: "Deny",
	}[verdict.decision]
	return payload


class _Handler(BaseHTTPRequestHandler):
	server_version = "PrivUp"
	sys_version = ""

	def log_message(self, fmt, *args):
		if self.server.verbose:  # type: ignore[attr-defined]
			super().log_message(fmt, *args)

	# -- helpers ---------------------------------------------------------

	def _host_is_local(self) -> bool:
		host = self.headers.get("Host", "")
		return urlparse(f"//{host}").hostname in {"localhost", "127.0.0.1", "::1"} or (
			host.split(":")[0] in _ALLOWED_HOSTS
		)

	def _send(self, status: int, body: bytes, content_type: str) -> None:
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.send_header("X-Content-Type-Options", "nosniff")
		# No policy text should ever leave this machine, including via a
		# referrer or an embedded frame.
		self.send_header("Referrer-Policy", "no-referrer")
		self.send_header("X-Frame-Options", "DENY")
		self.end_headers()
		if self.command != "HEAD":
			self.wfile.write(body)

	def _json(self, status: int, payload: dict) -> None:
		self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

	def _error(self, status: int, message: str) -> None:
		self._json(status, {"error": message})

	# -- routes ----------------------------------------------------------

	def do_GET(self) -> None:
		if not self._host_is_local():
			self._error(403, "This server only answers requests from this machine.")
			return

		path = urlparse(self.path).path
		if path == "/api/tags":
			self._json(200, {
				"tag_sets": [
					{"name": name, "description": description, "rules": count}
					for name, description, count in describe_tag_sets()
				]
			})
			return

		self._static(path)

	def do_HEAD(self) -> None:
		self.do_GET()

	def do_POST(self) -> None:
		if not self._host_is_local():
			self._error(403, "This server only answers requests from this machine.")
			return
		if urlparse(self.path).path != "/api/analyze":
			self._error(404, "No such endpoint.")
			return

		try:
			length = int(self.headers.get("Content-Length") or 0)
		except ValueError:
			self._error(400, "Content-Length was not a number.")
			return
		if length <= 0:
			self._error(400, "Nothing to analyze.")
			return
		if length > MAX_BODY_BYTES:
			self._error(413, "That document is too large for this box.")
			return

		try:
			request = json.loads(self.rfile.read(length).decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError):
			self._error(400, "Could not read that request.")
			return

		target = str(request.get("target") or "")
		tag_set = str(request.get("tags") or "generic")
		driver = request.get("driver") or None

		if not target.strip():
			self._error(400, "Paste a policy, or a link to one.")
			return

		try:
			self._json(200, analyze(target, tag_set, driver))
		except (UnknownDriverError, UnknownTagSetError) as exc:
			self._error(400, str(exc.args[0]))
		except DriverError as exc:
			self._error(502, str(exc))
		except Exception:  # pragma: no cover - last resort
			self._error(500, "Something went wrong running the pipeline.")

	def _static(self, path: str) -> None:
		relative = "index.html" if path in ("/", "") else path.lstrip("/")
		target = (STATIC_DIR / relative).resolve()

		# Refuse anything that escapes the static directory.
		if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
			self._error(404, "Not found.")
			return

		self._send(
			200,
			target.read_bytes(),
			_CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
		)


def build_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, verbose: bool = False):
	"""Create the HTTP server without starting it. Used by tests."""
	httpd = ThreadingHTTPServer((host, port), _Handler)
	httpd.verbose = verbose  # type: ignore[attr-defined]
	httpd.daemon_threads = True
	return httpd


def serve(
	host: str = DEFAULT_HOST,
	port: int = DEFAULT_PORT,
	open_browser: bool = True,
	verbose: bool = False,
) -> int:
	httpd = build_server(host, port, verbose)
	actual_host, actual_port = httpd.server_address[:2]
	url = f"http://{actual_host}:{actual_port}/"

	print(f"PrivUp is running at {url}")
	print("Nothing leaves this machine. Press Ctrl+C to stop.")

	if open_browser:
		threading.Timer(0.4, lambda: webbrowser.open(url)).start()

	try:
		httpd.serve_forever()
	except KeyboardInterrupt:
		print("\nStopped.")
	finally:
		httpd.server_close()
	return 0


def main(argv=None) -> int:
	parser = argparse.ArgumentParser(
		prog="privup-ui",
		description="Run the PrivUp web UI locally.",
	)
	parser.add_argument("--host", default=DEFAULT_HOST, help="interface to bind (default: 127.0.0.1)")
	parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default: 8420)")
	parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
	parser.add_argument("--verbose", action="store_true", help="log requests")
	args = parser.parse_args(argv)

	if args.host not in {"127.0.0.1", "localhost", "::1"}:
		print(
			f"Refusing to bind {args.host}. This UI shows policy text you pasted "
			"and is meant for this machine only."
		)
		return 2

	return serve(args.host, args.port, not args.no_browser, args.verbose)


if __name__ == "__main__":
	raise SystemExit(main())
