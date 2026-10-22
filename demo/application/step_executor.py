"""以隔离子进程执行单轮仿真。

子进程隔离是现有系统的重要兼容边界：每个场景可以使用独立的状态和输入
路径。本模块把环境变量协议封装起来，避免实验编排器了解这些实现细节。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SIMULATION_STEP_RESULT_PREFIX = "SIMULATION_STEP_RESULT="
INTERRUPT_TERMINATION_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class SimulationStepRequest:
    """运行单轮仿真所需的显式输入。"""

    state_dir: Path
    event_file: Path
    comment_pool_file: Path
    social_network_file: Path | None
    incremental_comment_count: int
    max_agents: int
    max_workers: int
    random_seed: int
    comment_temperature: float
    demo_dir: Path


def parse_simulation_step_result(output: str) -> dict:
    """从子进程标准输出中提取最后一个结构化单轮结果。"""

    for line in reversed(str(output).splitlines()):
        if not line.startswith(SIMULATION_STEP_RESULT_PREFIX):
            continue
        payload = line[len(SIMULATION_STEP_RESULT_PREFIX) :]
        try:
            result = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("单轮子进程返回的性能结果不是合法JSON。") from error
        if not isinstance(result, dict):
            raise ValueError("单轮子进程返回的结果必须是JSON对象。")
        return result
    raise ValueError("单轮子进程没有返回带标记的结构化结果。")


class SubprocessSimulationStepExecutor:
    """通过现有 ``simulation.runner`` 协议执行一轮仿真。"""

    def run(self, request: SimulationStepRequest) -> dict:
        if (
            isinstance(request.incremental_comment_count, bool)
            or not isinstance(request.incremental_comment_count, int)
            or request.incremental_comment_count < 1
        ):
            raise ValueError("incremental_comment_count 必须是正整数。")

        environment = self._build_environment(request)
        command = [
            sys.executable,
            "-m",
            "simulation.runner",
            "--max-agents",
            str(request.max_agents),
            "--workers",
            str(request.max_workers),
            "--incremental-comments",
            str(request.incremental_comment_count),
        ]
        process = subprocess.Popen(
            command,
            cwd=str(request.demo_dir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = process.communicate()
        except KeyboardInterrupt:
            # 2026/10/17，修改功能：用户中断父进程时主动回收当前
            # 仿真子进程，避免PowerShell已经返回但后台python仍运行。
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    # Ctrl+C可能已经同时结束Windows控制台子进程。
                    pass
            try:
                process.communicate(
                    timeout=INTERRUPT_TERMINATION_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
        if process.returncode != 0:
            output_parts = []
            if stdout.strip():
                output_parts.append(f"标准输出：\n{stdout.strip()}")
            if stderr.strip():
                output_parts.append(f"异常输出：\n{stderr.strip()}")
            message = "\n\n".join(output_parts) or "子进程未返回错误信息。"
            raise RuntimeError(f"场景时间步运行失败：{message}")
        return parse_simulation_step_result(stdout)

    @staticmethod
    def _build_environment(request: SimulationStepRequest) -> dict[str, str]:
        environment = os.environ.copy()
        environment["SIMULATION_STATE_DIR"] = str(request.state_dir.resolve())
        environment["SIMULATION_EVENT_FILE"] = str(request.event_file.resolve())
        environment["SIMULATION_COMMENT_POOL_FILE"] = str(
            request.comment_pool_file.resolve()
        )
        if request.social_network_file is not None:
            environment["SIMULATION_SOCIAL_NETWORK_FILE"] = str(
                request.social_network_file.resolve()
            )
        environment["SIMULATION_RANDOM_SEED"] = str(request.random_seed)
        environment["SIMULATION_COMMENT_TEMPERATURE"] = str(
            request.comment_temperature
        )
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

