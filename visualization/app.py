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
from visualization.historical.service import (
    build_comparison as build_historical_comparison,
    load_dashboard as load_historical_dashboard,
    load_reference_for_request,
)
from visualization.historical.real_trend_repository import list_real_trends
from visualization.shared.experiment_catalog import list_experiments
from visualization.shared.network.service import (
    build_comment_cascade,
    build_comment_catalog,
    build_network_view,
    build_report_summary,
)
from visualization.strategy.service import load_dashboard as load_strategy_dashboard


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
            if parsed.path == "/api/catalog":
                mode = parse_qs(parsed.query).get("mode", [""])[0] or None
                self._send_json(
                    {"experiments": list_experiments(mode=mode)}
                )
                return
            if parsed.path == "/api/historical/real-trends":
                self._send_json({"real_trends": list_real_trends()})
                return
            if parsed.path == "/api/historical/real-trend":
                query = parse_qs(parsed.query)
                self._send_json(
                    load_reference_for_request(
                        experiment_id=query.get("experiment_id", [""])[0],
                        event_id=query.get("event_id", [""])[0],
                    )
                )
                return
            if parsed.path in {
                "/api/historical/dashboard",
                "/api/historical/comparison",
            }:
                experiment_id = parse_qs(parsed.query).get(
                    "experiment_id", [""]
                )[0]
                if not experiment_id:
                    raise ValueError("缺少 experiment_id")
                if parsed.path == "/api/historical/dashboard":
                    self._send_json(load_historical_dashboard(experiment_id))
                else:
                    self._send_json(build_historical_comparison(experiment_id))
                return
            if parsed.path == "/api/strategy/dashboard":
                experiment_id = parse_qs(parsed.query).get(
                    "experiment_id", [""]
                )[0]
                if not experiment_id:
                    raise ValueError("缺少 experiment_id")
                self._send_json(load_strategy_dashboard(experiment_id))
                return
            if parsed.path in {
                "/api/network/report",
                "/api/network/view",
                "/api/network/comments",
                "/api/network/cascade",
            }:
                query = parse_qs(parsed.query)
                experiment_id = query.get("experiment_id", [""])[0]
                if not experiment_id:
                    raise ValueError("缺少 experiment_id")
                scenario_id = query.get("scenario", [""])[0] or None
                if parsed.path == "/api/network/report":
                    self._send_json(build_report_summary(experiment_id))
                elif parsed.path == "/api/network/view":
                    raw_step = query.get("step", [""])[0]
                    step = int(raw_step) if raw_step else None
                    self._send_json(
                        build_network_view(experiment_id, scenario_id, step)
                    )
                elif parsed.path == "/api/network/comments":
                    self._send_json(
                        build_comment_catalog(experiment_id, scenario_id)
                    )
                else:
                    comment_id = query.get("comment_id", [""])[0]
                    self._send_json(
                        build_comment_cascade(
                            experiment_id, scenario_id, comment_id
                        )
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

