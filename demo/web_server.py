"""Minimal stdlib HTTP adapter for the Simulation2 web API.

Run with ``python demo/web_server.py``. The adapter only serializes calls to
``web_api``; it does not implement simulation logic.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse

import web_api


SESSION_ACTION_RE = re.compile(
    r"^/api/sessions/([0-9A-Za-z_\-]+)/(start|step|continue|pause|resume|rollback|restart|run|announcement)$"
)
SESSION_GET_RE = re.compile(r"^/api/sessions/([0-9A-Za-z_\-]+)$")
WEB_ROOT = Path(__file__).resolve().parent.parent / "visualization" / "web"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, payload, status=HTTPStatus.OK):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _serve_static(self, path):
        relative = unquote(path).lstrip("/") or "index.html"
        requested = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in requested.parents and requested != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            f"{content_type or 'application/octet-stream'}; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _run(self, action):
        try:
            if action == "defaults":
                payload = web_api.prepare_web_inputs()
                payload["event_default"] = web_api.get_event_web_default()
                payload["official_default"] = (
                    web_api.get_official_content_web_default()
                )
                self._send_json(payload)
                return
            if action == "preview":
                body = self._read_json()
                self._send_json(
                    web_api.prepare_web_inputs(
                        web_event_input=body.get("web_event_input"),
                        official_content_input=body.get(
                            "official_content_input"
                        ),
                        entry_timing_input=body.get("entry_timing_input"),
                        announcement_timeline_input=body.get(
                            "announcement_timeline_input"
                        ),
                    )
                )
                return
            if action == "create":
                body = self._read_json()
                self._send_json(
                    web_api.create_web_experiment(
                        web_event_input=body.get("web_event_input"),
                        official_content_input=body.get(
                            "official_content_input"
                        ),
                        entry_timing_input=body.get("entry_timing_input"),
                        announcement_timeline_input=body.get(
                            "announcement_timeline_input"
                        ),
                        selected_strategy_id=body.get(
                            "selected_strategy_id",
                            "fact_report",
                        ),
                    ),
                    HTTPStatus.CREATED,
                )
                return
            if action == "list":
                self._send_json(
                    {"sessions": web_api.list_web_experiments()}
                )
                return
            raise ValueError("不支持的 API 操作")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _session(self, experiment_id, action):
        try:
            body = self._read_json()
            if action == "start":
                payload = web_api.start_web_experiment(experiment_id)
            elif action == "step":
                payload = web_api.step_web_experiment(experiment_id)
            elif action == "continue":
                payload = web_api.continue_web_experiment(experiment_id)
            elif action == "pause":
                payload = web_api.pause_web_experiment(experiment_id)
            elif action == "resume":
                payload = web_api.resume_web_experiment(experiment_id)
            elif action == "rollback":
                payload = web_api.rollback_web_experiment(
                    experiment_id,
                    steps=body.get("steps", 1),
                )
            elif action == "restart":
                payload = web_api.restart_web_experiment(experiment_id)
            elif action == "run":
                payload = web_api.run_all_web_experiment(experiment_id)
            elif action == "announcement":
                payload = web_api.add_web_announcement(
                    experiment_id,
                    round_no=body.get("round"),
                    official_statement=body.get(
                        "official_statement",
                        "",
                    ),
                    official_statement_status=body.get(
                        "official_statement_status",
                        "clear",
                    ),
                )
            elif action == "status":
                payload = web_api.get_web_experiment_status(experiment_id)
            else:
                raise ValueError(f"不支持的动作：{action}")
            self._send_json(payload)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._send_json(
                {"error": str(error)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/input/defaults":
            self._run("defaults")
            return
        if path == "/api/sessions":
            self._run("list")
            return
        match = SESSION_GET_RE.match(path)
        if match:
            self._session(match.group(1), "status")
            return
        if not path.startswith("/api/"):
            self._serve_static(path)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/input/preview":
            self._run("preview")
            return
        if path == "/api/sessions":
            self._run("create")
            return
        match = SESSION_ACTION_RE.match(path)
        if match:
            self._session(match.group(1), match.group(2))
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format_string, *args):
        print(f"[web server] {format_string % args}")


def main():
    parser = argparse.ArgumentParser(description="Simulation2 web API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Simulation2 web API: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb API server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
