"""启动第二十六次联调社交网络传播专题网页。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import DEFAULT_HOST, DEFAULT_PORT, EXPERIMENT_ID, STATIC_DIR
from report_data import (
    build_comment_cascade,
    build_comment_catalog,
    build_network_view,
    build_report_summary,
)


class SocialNetworkReportHandler(BaseHTTPRequestHandler):
    """提供专题页面静态资源和只读分析接口。"""

    def _send_json(
        self, payload: object, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, relative_path: str) -> None:
        """限制静态资源只能从专题目录读取。"""
        static_root = STATIC_DIR.resolve()
        requested = (STATIC_DIR / relative_path).resolve()
        if requested != static_root and static_root not in requested.parents:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = requested.read_bytes()
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # 2026/09/06 社交网络传播可视化，新增功能：提供网络、评论目录和单评论传播链只读接口。
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/report":
                self._send_json(build_report_summary())
                return
            if parsed.path == "/api/network":
                scenario_id = query.get("scenario", ["no_response"])[0]
                step = int(query.get("step", ["10"])[0])
                self._send_json(build_network_view(scenario_id, step))
                return
            if parsed.path == "/api/comments":
                scenario_id = query.get("scenario", ["no_response"])[0]
                self._send_json(build_comment_catalog(scenario_id))
                return
            if parsed.path == "/api/cascade":
                scenario_id = query.get("scenario", ["no_response"])[0]
                comment_id = query.get("comment_id", [""])[0]
                self._send_json(
                    build_comment_cascade(scenario_id, comment_id)
                )
                return
            if parsed.path in {"/", "/index.html"}:
                self._serve_static("index.html")
                return
            self._serve_static(parsed.path.lstrip("/"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._send_json(
                {"error": str(error)}, status=HTTPStatus.BAD_REQUEST
            )

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[社交网络专题] {format_string % args}")


def main() -> None:
    """启动不依赖第三方包的本地只读专题服务。"""
    parser = argparse.ArgumentParser(description="第二十六次联调社交网络专题")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # 启动前先读取摘要，使缺失数据在打开浏览器之前明确报错。
    build_report_summary()
    server = ThreadingHTTPServer(
        (args.host, args.port), SocialNetworkReportHandler
    )
    url = f"http://{args.host}:{args.port}"
    print(f"第二十六次联调社交网络专题已启动：{url}")
    print(f"实验编号：{EXPERIMENT_ID}")
    print("按 Ctrl+C 停止服务。实验结果始终以只读方式加载。")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n社交网络专题服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
