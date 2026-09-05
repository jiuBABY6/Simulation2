"""启动无需第三方依赖的历史趋势复现本地网页。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from comparison_service import compare_negative_trends
from config import DEFAULT_HOST, DEFAULT_PORT, REAL_DATA_PATH, STATIC_DIR
from simulation_data_loader import list_experiments, load_experiment


def _load_real_trend() -> dict[str, object]:
    if not REAL_DATA_PATH.is_file():
        raise FileNotFoundError(
            "缺少处理后的真实趋势数据，请先运行 python visualization/real_data_processor.py"
        )
    return json.loads(REAL_DATA_PATH.read_text(encoding="utf-8"))


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

    def _serve_static(self, relative_path: str) -> None:
        requested = (STATIC_DIR / relative_path).resolve()
        if STATIC_DIR.resolve() not in requested.parents and requested != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # 2026/09/02 历史趋势可视化，新增功能：提供只读实验、真实趋势和对照接口。
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/experiments":
                self._send_json({"experiments": list_experiments()})
                return
            if parsed.path == "/api/real-trend":
                self._send_json(_load_real_trend())
                return
            if parsed.path in {"/api/dashboard", "/api/comparison"}:
                experiment_id = parse_qs(parsed.query).get("experiment_id", [""])[0]
                if not experiment_id:
                    raise ValueError("缺少 experiment_id")
                simulation = load_experiment(experiment_id)
                if parsed.path == "/api/dashboard":
                    self._send_json(simulation)
                else:
                    self._send_json(
                        compare_negative_trends(simulation, _load_real_trend())
                    )
                return
            if parsed.path in {"/", "/index.html"}:
                self._serve_static("index.html")
                return
            self._serve_static(parsed.path.lstrip("/"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._send_error_json(error)

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[可视化] {format_string % args}")


# 2026/09/02 历史趋势可视化，新增功能：启动隔离的本地只读展示服务。
def main() -> None:
    parser = argparse.ArgumentParser(description="历史趋势复现数据展示")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), VisualizationHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"历史趋势复现可视化已启动：{url}")
    print("按 Ctrl+C 停止服务。历史实验文件始终以只读方式加载。")
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

