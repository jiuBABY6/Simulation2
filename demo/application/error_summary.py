"""面向控制台的运行错误摘要。"""


def summarize_scenario_error(error: Exception, max_length: int = 160) -> str:
    """返回单行错误摘要，完整异常仍由调用方保存。"""

    message = str(error)
    if "HTTP 402" in message or "Insufficient Balance" in message:
        return "DeepSeek HTTP 402：余额不足（Insufficient Balance）"
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    summary = lines[-1] if lines else error.__class__.__name__
    if len(summary) > max_length:
        return f"{summary[:max_length]}……"
    return summary

