"""统一可视化入口：路由历史复现、五策略和共享网络页面。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 支持现有的 ``python visualization/app.py`` 启动方式，同时统一使用包导入。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visualization.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HISTORICAL_STATIC_DIR,
    NETWORK_STATIC_DIR,
    PORTAL_DIR,
    STRATEGY_STATIC_DIR,
)
from visualization.api_router import API_PATHS, dispatch_api


class VisualizationHandler(BaseHTTPRequestHandler):
    """提供静态页面和只读 JSON API。"""

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_error_json(self, error: Exception) -> None:
        self._send_json(
            {"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR
        )

    def _serve_static(self, static_dir: Path, relative_path: str) -> None:
        static_root = static_dir.resolve()
        requested = (static_dir / relative_path).resolve()
        if static_root not in requested.parents and requested != static_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        media_type = content_type or "application/octet-stream"
        self.send_header("Content-Type", f"{media_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # 三层可视化 API：业务页面各自拥有命名空间，网络分析保持共享。
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in API_PATHS:
                self._send_json(
                    dispatch_api(parsed.path, parse_qs(parsed.query))
                )
                return
            if parsed.path in {"/", "/index.html"}:
                self._serve_static(PORTAL_DIR, "index.html")
                return
            if parsed.path.startswith("/portal/"):
                self._serve_static(
                    PORTAL_DIR, parsed.path.removeprefix("/portal/")
                )
                return
            if parsed.path in {"/historical", "/historical/"}:
                self._serve_static(HISTORICAL_STATIC_DIR, "index.html")
                return
            if parsed.path.startswith("/historical/"):
                self._serve_static(
                    HISTORICAL_STATIC_DIR,
                    parsed.path.removeprefix("/historical/"),
                )
                return
            if parsed.path in {"/strategy", "/strategy/"}:
                self._serve_static(STRATEGY_STATIC_DIR, "index.html")
                return
            if parsed.path.startswith("/strategy/"):
                self._serve_static(
                    STRATEGY_STATIC_DIR,
                    parsed.path.removeprefix("/strategy/"),
                )
                return
            if parsed.path in {"/network", "/network/"}:
                self._serve_static(NETWORK_STATIC_DIR, "index.html")
                return
            if parsed.path.startswith("/network/"):
                self._serve_static(
                    NETWORK_STATIC_DIR,
                    parsed.path.removeprefix("/network/"),
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            self._send_error_json(error)

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[可视化] {format_string % args}")


# 2026/10/10，三层可视化共用一个只读 HTTP 入口。
def main() -> None:
    parser = argparse.ArgumentParser(description="舆情模拟统一可视化入口")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), VisualizationHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"舆情模拟统一可视化已启动：{url}")
    print("按 Ctrl+C 停止服务。实验文件始终以只读方式加载。")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n可视化服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

