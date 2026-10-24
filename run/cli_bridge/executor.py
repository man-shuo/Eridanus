# -*- coding: utf-8 -*-
import asyncio
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Tuple, Dict, Any

from .session_manager import get_session_id, save_session, clear_session

# ANSI 转义序列正则，用于剥离终端彩色字符
ANSI_REGEX = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')

# 正在运行的任务映射：key -> {"process": Popen, "provider": str, "start_time": float}
RUNNING_TASKS: Dict[str, Dict[str, Any]] = {}


def strip_ansi(text: str) -> str:
    """去除终端 ANSI 颜色与控制序列"""
    if not text:
        return ""
    return ANSI_REGEX.sub('', text)


def extract_session_id(text: str) -> Optional[str]:
    """从文本中提取 Codex / Claude 的 session id (UUID)"""
    if not text:
        return None
    # 优先匹配明确标注的 session id
    explicit_match = re.search(r'session\s*id[:\s]+([0-9a-fA-F-]{32,36})', text, re.IGNORECASE)
    if explicit_match:
        return explicit_match.group(1).strip()
    # 通用 UUID 匹配
    uuid_match = re.findall(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', text)
    if uuid_match:
        return uuid_match[-1]
    return None


def clean_cli_output(text: str, max_length: int = 6000) -> str:
    """清理 CLI 终端输出中的无用日志与冗余头部"""
    text = strip_ansi(text).strip()
    if not text:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        # 常见噪声行过滤
        if lower.startswith("reading additional input from stdin"):
            continue
        if lower.startswith("openai codex v"):
            continue
        if lower.startswith("tokens used") or (lower.isdigit() and cleaned_lines and cleaned_lines[-1] == "tokens used"):
            continue
        if lower.startswith("sandbox:") or lower.startswith("reasoning effort:") or lower.startswith("reasoning summaries:"):
            continue
        if lower.startswith("workdir:") or lower.startswith("provider:") or lower.startswith("approval:"):
            continue
        if lower.startswith("session id:"):
            continue
        if lower == "--------":
            continue
        if lower.startswith("warning: codex is ignoring"):
            continue
        if "is ignored." in lower and "config.toml" in lower:
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()
    if len(result) > max_length:
        result = result[:max_length] + f"\n\n... [输出较长，已截断前 {max_length} 字符]"
    return result


def is_session_expired_error(output: str) -> bool:
    """判断是否为会话失效/不存在的错误"""
    lower = output.lower()
    keywords = [
        "session not found",
        "invalid session",
        "could not find session",
        "cannot find session",
        "no session found",
        "unknown session",
        "session expired"
    ]
    return any(k in lower for k in keywords)


def find_executable(cmd_name: str) -> Optional[str]:
    """在系统 PATH 中定位可执行文件，支持 Windows 下优先查找 .cmd / .exe"""
    which_res = shutil.which(cmd_name)
    if which_res:
        return which_res
    if os.name == "nt":
        for ext in [".cmd", ".CMD", ".exe", ".EXE", ".bat", ".BAT"]:
            candidate = shutil.which(cmd_name + ext)
            if candidate:
                return candidate
    return None


def terminate_running_task(session_key: str) -> bool:
    """终止指定 key 正在运行的底层 CLI 进程及其所有子进程"""
    task = RUNNING_TASKS.get(session_key)
    if not task:
        return False
    proc = task.get("process")
    if not proc or proc.poll() is not None:
        RUNNING_TASKS.pop(session_key, None)
        return False

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        else:
            proc.kill()
    except Exception:
        pass
    finally:
        RUNNING_TASKS.pop(session_key, None)
    return True


def is_task_running(session_key: str) -> bool:
    """检查指定 key 是否有任务在运行"""
    task = RUNNING_TASKS.get(session_key)
    if not task:
        return False
    proc = task.get("process")
    if proc and proc.poll() is None:
        return True
    RUNNING_TASKS.pop(session_key, None)
    return False


async def run_cli_command(
    command_str: str,
    prompt: str,
    timeout: float,
    provider: str,
    session_key: str = "",
    reset_session: bool = False,
    max_output_length: int = 6000,
    auto_fallback: bool = True
) -> str:
    """执行底层 CLI 命令并返回经过清洗的结果文本"""
    # 检查是否已有同名任务在跑
    if session_key and is_task_running(session_key):
        return "当前已有一个 CLI 任务正在为您运行中，请等待其完成或发送 `/codex stop`（或 `/claude stop`）终止当前任务。"

    # 如果显式指定了重置会话
    if reset_session and session_key:
        clear_session(session_key)

    raw_args = shlex.split(command_str, posix=os.name != "nt")
    if not raw_args:
        return "错误：CLI 命令配置为空。"

    base_exe = raw_args[0]
    executable = find_executable(base_exe)
    if not executable:
        return f"错误：未在系统环境变量 PATH 中找到可执行命令 `{base_exe}`，请检查是否已正确安装该 CLI 工具。"

    # 解析 session id
    saved_session_id = None if reset_session else (get_session_id(session_key) if session_key else None)
    is_resume = bool(saved_session_id)

    # 临时文件，用于 codex 捕获最终纯净回复
    temp_last_msg_file = None
    if provider == "codex":
        fd, temp_last_msg_file = tempfile.mkstemp(prefix="codex_last_msg_", suffix=".txt")
        os.close(fd)

    try:
        # 构建执行参数列表
        cmd_args = [executable]
        extra_options = raw_args[1:]

        if provider == "codex":
            # 过滤掉可能遗留的不合法参数
            extra_options = [opt for opt in extra_options if opt != "--yolo"]
            filtered_opts = [opt for opt in extra_options if opt not in ("exec", "resume")]
            if is_resume:
                cmd_args.extend(["exec", "resume"])
                cmd_args.extend(filtered_opts)
                if temp_last_msg_file:
                    cmd_args.extend(["-o", temp_last_msg_file])
                cmd_args.append(saved_session_id)
                cmd_args.append(prompt)
            else:
                cmd_args.append("exec")
                cmd_args.extend(filtered_opts)
                if temp_last_msg_file:
                    cmd_args.extend(["-o", temp_last_msg_file])
                cmd_args.append(prompt)

        elif provider == "claude":
            cmd_args.extend(extra_options)
            if is_resume:
                cmd_args.extend(["--resume", saved_session_id])
            cmd_args.append(prompt)

        else:
            cmd_args.extend(extra_options)
            cmd_args.append(prompt)

        # 执行子进程
        def _invoke() -> Tuple[int, bytes, bytes]:
            proc = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=os.getcwd()
            )
            if session_key:
                RUNNING_TASKS[session_key] = {
                    "process": proc,
                    "provider": provider,
                    "start_time": time.time()
                }
            try:
                out, err = proc.communicate(timeout=timeout)
                return proc.returncode, out or b"", err or b""
            finally:
                if session_key:
                    RUNNING_TASKS.pop(session_key, None)

        try:
            returncode, stdout_bytes, stderr_bytes = await asyncio.to_thread(_invoke)
        except subprocess.TimeoutExpired:
            if session_key:
                terminate_running_task(session_key)
            return f"CLI 执行超时（超过预设的 {int(timeout)} 秒），已自动中止进程。"

        # 解码输出（优先 utf-8，其次系统编码）
        def decode_bytes(b: bytes) -> str:
            if not b:
                return ""
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return b.decode("mbcs" if os.name == "nt" else "gbk", errors="replace")

        stdout_text = decode_bytes(stdout_bytes)
        stderr_text = decode_bytes(stderr_bytes)
        combined_text = (stdout_text + "\n" + stderr_text).strip()

        # 尝试从 stderr / stdout 中捕获 session id 并保存
        captured_session_id = extract_session_id(stderr_text) or extract_session_id(stdout_text)
        if captured_session_id and session_key:
            save_session(session_key, captured_session_id, prompt)

        # 检查是否因为旧 session 失效导致 resume 失败
        if is_resume and auto_fallback and returncode != 0 and is_session_expired_error(combined_text):
            clear_session(session_key)
            retry_res = await run_cli_command(
                command_str=command_str,
                prompt=prompt,
                timeout=timeout,
                provider=provider,
                session_key=session_key,
                reset_session=True,
                max_output_length=max_output_length,
                auto_fallback=False
            )
            return f"[提示：检测到旧会话已失效，已自动为您重置并开启新会话]\n\n" + retry_res

        # 优先读取 codex 的 last message 纯净输出文件
        last_message_content = ""
        if temp_last_msg_file and os.path.exists(temp_last_msg_file):
            try:
                with open(temp_last_msg_file, "r", encoding="utf-8") as f:
                    last_message_content = f.read().strip()
            except Exception:
                pass

        if last_message_content:
            final_reply = last_message_content
        else:
            final_reply = clean_cli_output(combined_text or stdout_text, max_length=max_output_length)

        if not final_reply:
            if returncode == 0:
                return "CLI 执行完成，但未产生任何控制台输出。"
            else:
                return f"CLI 执行异常退出 (退出码 {returncode})。\n{stderr_text[:500]}"

        return final_reply

    finally:
        # 清理临时文件
        if temp_last_msg_file and os.path.exists(temp_last_msg_file):
            try:
                os.remove(temp_last_msg_file)
            except OSError:
                pass
