# -*- coding: utf-8 -*-
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from developTools.utils.logger import get_logger
from framework_common.utils.install_and_import import install_and_import

logger = get_logger()

parent_dir = os.path.dirname(os.getcwd())
custom_git_path = os.path.join(parent_dir, "environments", "MinGit", "cmd", "git.exe")
if os.path.exists(custom_git_path):
    git_path = custom_git_path
else:
    git_path = "git"

custom_python_path = os.path.join(parent_dir, "environments", "Python311", "python.exe")
python_path = sys.executable

try:
    from pip._internal.cli.main import main as pip_main
except ImportError:
    pip_main = None

if pip_main is not None:
    try:
        pip_main(['config', 'set', 'global.index-url', 'https://mirrors.aliyun.com/pypi/simple/'])
    except Exception:
        pass

SOURCES = [
    "https://github.com/avilliai/Eridanus.git",
    "https://gitcode.com/faasf/Eridanus.git",
    "https://github.akams.cn/https://github.com/avilliai/Eridanus.git",
    "https://mirror.ghproxy.com/https://github.com/avilliai/Eridanus",
    "https://ghfast.top/https://github.com/avilliai/Eridanus.git",
    "https://gh.llkk.cc/https://github.com/avilliai/Eridanus.git"
]

YAML_BACKUP_DIR = os.path.join("temp", "yaml_backup")

try:
    from ruamel.yaml import YAML
except Exception:
    if pip_main is not None:
        try:
            pip_main(['install', 'ruamel.yaml'])
        except Exception:
            pass
    from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def setup_git_proxy_if_interactive():
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        proxy = ym.common_config.basic_config.get("proxy", {}).get("http_proxy")
        if proxy:
            logger.warning(f"检测到设置了代理 {proxy}，是否要为 git 配置代理？输入 y 确认，输入 n 清除代理，回车不做修改。gitcode 源不需要代理。")
            set_proxy = input("在此输入：").strip().lower()
            if set_proxy == "y":
                subprocess.run([git_path, "config", "--global", "http.proxy", proxy], check=True)
                subprocess.run([git_path, "config", "--global", "https.proxy", proxy], check=True)
                logger.info("Git 代理配置成功。")
            elif set_proxy == "n":
                subprocess.run([git_path, "config", "--global", "--unset", "http.proxy"], stderr=subprocess.DEVNULL)
                subprocess.run([git_path, "config", "--global", "--unset", "https.proxy"], stderr=subprocess.DEVNULL)
                logger.info("Git 全局代理已清除。")
    except Exception as e:
        logger.debug(f"Git 代理交互配置跳过或异常: {e}")


def merge_dicts(old, new):
    for k, v in old.items():
        if isinstance(v, dict) and k in new and isinstance(new[k], dict):
            merge_dicts(v, new[k])
        elif isinstance(v, list) and k in new and isinstance(new[k], list):
            if k in ["api_keys", "sdUrl", "其他默认绘图参数", "card_index", "steam_api_key", "nano_banana_key", "固定入群欢迎", "apikey"]:
                new[k] = v
            elif k.startswith("page"):
                logger.warning("当前任务为菜单，使用最新配置覆盖旧配置。")
            else:
                try:
                    new[k] = list(dict.fromkeys(new[k] + v))
                except Exception:
                    logger.error("列表合并出错，默认用最新配置")
        elif k in new and not isinstance(v, type(new[k])) and not isinstance(new[k], type(v)):
            continue
        elif k in new:
            new[k] = v
        else:
            # 旧配置中有但新模板中没有的自定义字段，完整保留
            new[k] = v


def conflict_file_dealter(file_old, file_new):
    with open(file_old, 'r', encoding="utf-8") as file:
        old_data = yaml.load(file)
    with open(file_new, 'r', encoding="utf-8") as file:
        new_data = yaml.load(file)
    if old_data is not None and new_data is not None:
        merge_dicts(old_data, new_data)
        with open(file_new, 'w', encoding="utf-8") as file:
            yaml.dump(new_data, file)


def print_result_banner(status: str, detail: str = ""):
    line = "=" * 66
    if status == "UP_TO_DATE":
        msg = [
            line,
            "【当前已经是最新版本！】(Already Up-To-Date)",
            line,
            "您的代码库已与远程仓库完全同步，无需额外更新。",
            "所有配置文件与资源文件完好，您可以正常启动 Bot！",
            line
        ]
        for m in msg:
            logger.info(m)
    elif status == "SUCCESS":
        msg = [
            line,
            "【恭喜！代码已成功更新至最新版本！】(Update Success)",
            line,
            "本次更新已顺利完成，冲突资源与配置已安全处理与合并。",
            "若更新了核心框架模块，请重启 Bot 使其生效！",
            line
        ]
        for m in msg:
            logger.info(m)
    else:
        msg = [
            line,
            "【注意：未能完全更新至最新版本】(Update Incomplete)",
            line,
            "更新过程中可能遇到了未自动解决的冲突或网络波动。",
            f"原因/详情: {detail}" if detail else "请检查网络连接、Git 代理或查看上方的详细日志。",
            "我们已尽力保障您的 yaml 配置文件安全，没有丢失。",
            line
        ]
        for m in msg:
            logger.error(m)


def run_git_command(args: list) -> tuple:
    full_cmd = [git_path] + args
    try:
        p = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        out_str = stdout.decode('utf-8', errors='ignore')
        err_str = stderr.decode('utf-8', errors='ignore')
        return p.returncode, out_str, err_str
    except Exception as e:
        return -1, "", str(e)


def is_git_up_to_date(stdout: str, stderr: str) -> bool:
    combined = (stdout + "\n" + stderr).lower()
    return "already up to date" in combined or "已经是最新" in combined or "已经是最新版本" in combined


def is_git_pull_success(returncode: int, stdout: str, stderr: str) -> bool:
    if is_git_up_to_date(stdout, stderr):
        return True
    combined = (stdout + "\n" + stderr).lower()
    if returncode == 0:
        if "conflict" not in combined and "error:" not in combined and "fatal:" not in combined:
            return True
    if "updating " in combined and "files changed" in combined and "error:" not in combined and "fatal:" not in combined:
        return True
    return False


def parse_git_conflicts(output: str) -> list:
    files = set()
    lines = output.splitlines()
    in_overwrite_block = False

    for line in lines:
        stripped = line.strip()

        m = re.search(r'error:\s*Your local changes to the following files would be overwritten by merge:\s*', stripped, re.IGNORECASE)
        if m or "下列文件的本地更改将被合并覆盖" in stripped or "would be overwritten by merge" in stripped:
            in_overwrite_block = True
            continue

        if in_overwrite_block:
            if stripped.startswith("Please commit your changes") or stripped.startswith("Aborting") or stripped.startswith("请在合并前提交") or stripped.startswith("终止"):
                in_overwrite_block = False
                continue
            if stripped and not stripped.startswith("error:") and not stripped.startswith("fatal:"):
                files.add(stripped.replace("\\", "/"))
                continue

        m = re.search(r'error:\s*The following untracked working tree files would be overwritten by merge:\s*', stripped, re.IGNORECASE)
        if m or "下列未跟踪的工作区文件将被合并覆盖" in stripped:
            in_overwrite_block = True
            continue

        m = re.search(r'CONFLICT\s*\(.*?\):\s*Merge conflict in\s+(.*)', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'conflict in\s+(.*)', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'CONFLICT\s*\(modify/delete\):\s*(.*?)\s+deleted in', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

        m = re.search(r'error:\s*unable to unlink\s+[\'"]?(.*?)[\'"]?:\s*', stripped, re.IGNORECASE)
        if m:
            files.add(m.group(1).strip().replace("\\", "/"))
            continue

    clean_files = []
    for f in files:
        f_clean = f.strip().strip("'\"")
        if f_clean and not f_clean.startswith("fatal:") and not f_clean.startswith("error:"):
            clean_files.append(f_clean)
    return clean_files


def clean_and_backup_file(file_path: str, backed_up_yamls: dict) -> bool:
    if not os.path.exists(file_path):
        return True

    normalized = file_path.replace("\\", "/")
    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".yaml", ".yml"]:
        try:
            os.makedirs(YAML_BACKUP_DIR, exist_ok=True)
            safe_name = normalized.replace("/", "__")
            backup_path = os.path.join(YAML_BACKUP_DIR, safe_name)
            shutil.copy2(file_path, backup_path)
            backed_up_yamls[normalized] = backup_path
            logger.info(f"已安全备份本地配置文件: {file_path} -> {backup_path}")
            os.remove(file_path)
            return True
        except Exception as e:
            logger.error(f"备份或移除本地 yaml 文件失败: {file_path}, error: {e}")
            return False
    else:
        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path, ignore_errors=True)
            else:
                os.remove(file_path)
            logger.warning(f"为排除拉取冲突，已自动清理冲突资源文件: {file_path}")
            return True
        except Exception as e:
            logger.error(f"清理冲突资源文件失败: {file_path}, error: {e}")
            return False


def restore_or_merge_yamls(backed_up_yamls: dict, pull_succeeded: bool):
    if not backed_up_yamls:
        return

    logger.info("开始处理暂存备份的配置文件...")
    for orig_rel_path, backup_path in list(backed_up_yamls.items()):
        if not os.path.exists(backup_path):
            continue

        if pull_succeeded:
            if os.path.exists(orig_rel_path):
                logger.info(f"正在智能合并配置更新: {orig_rel_path}")
                try:
                    conflict_file_dealter(backup_path, orig_rel_path)
                    logger.info(f"配置文件合并成功: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"合并配置文件失败 {orig_rel_path}: {e}，将保留原配置")
                    try:
                        shutil.copy2(backup_path, orig_rel_path)
                    except Exception:
                        pass
            else:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(orig_rel_path)), exist_ok=True)
                    shutil.copy2(backup_path, orig_rel_path)
                    logger.info(f"远程无新同名配置，已完整还原原配置文件: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"还原原配置文件失败: {orig_rel_path}, error: {e}")
        else:
            if not os.path.exists(orig_rel_path):
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(orig_rel_path)), exist_ok=True)
                    shutil.copy2(backup_path, orig_rel_path)
                    logger.warning(f"更新未成功，已安全恢复原配置文件: {orig_rel_path}")
                except Exception as e:
                    logger.error(f"恢复原配置文件失败: {orig_rel_path}, error: {e}")


def is_ai_configured() -> bool:
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        if not hasattr(ym, "mai_reply"):
            return False
        cfg = ym.mai_reply.config
        if not cfg or not cfg.get("enable", True):
            return False
        llm = cfg.get("llm", {})
        provider = llm.get("provider", "openai")
        provider_cfg = llm.get(provider, {})
        keys = provider_cfg.get("api_keys", [])
        if not keys:
            return False
        first_key = str(keys[0]).strip()
        if not first_key or first_key in ["xxx", "YOUR_GEMINI_API_KEY", "YOUR_OPENAI_API_KEY"]:
            return False
        return True
    except Exception:
        return False


def ai_solve_git_update(source_url: str, initial_stdout: str, initial_stderr: str) -> tuple:
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        from run.mai_reply.service.llm_client import LLMClient
        ym = YAMLManager.get_instance()
        client = LLMClient(ym)
    except Exception as e:
        logger.error(f"初始化 AI 客户端失败: {e}")
        return False, f"AI 初始化失败: {e}"

    backed_up_yamls = {}
    history = []

    system_prompt = (
        "你是一个专业的 Git 诊断与自动化更新解决助手。当前用户正在更新开源项目，但遇到了 Git 冲突或错误。\n"
        "请记住：用户是技术小白，你需要全自动调用工具解决问题，直至成功 pull 到最新代码。\n"
        "规则：\n"
        "1. 遇到 gif, png, jpg, txt, py 等非 yaml 资源或代码冲突，调用 clean_conflicts 直接删除它们，以便顺利更新。\n"
        "2. 遇到 yaml, yml 配置文件，必须调用 clean_conflicts（系统会自动将其备份并在更新后进行安全合并，绝不丢失配置）。\n"
        "3. 在清理冲突文件后，必须再次调用 git_pull 尝试拉取。\n"
        "4. 如果更新已经是最新 (already up to date) 或更新成功，向用户汇报已成功。\n"
        "5. 最多进行 5 轮交互，不要死循环。"
    )

    tools_schema = [
        {
            "name": "clean_conflicts",
            "description": "清理导致 Git 冲突的文件或目录。对于 yaml 文件会自动备份以便后续合并，对于 gif/png/txt/py 等文件会直接移除以允许 pull。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要清理的冲突文件或目录相对路径列表，例如 ['run/test.gif', 'config.yaml']"
                    }
                },
                "required": ["file_paths"]
            }
        },
        {
            "name": "git_pull",
            "description": "执行 git pull 操作从指定源拉取最新代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "description": "Git 远程仓库地址"
                    }
                }
            }
        },
        {
            "name": "git_status",
            "description": "查看当前的 git status 输出。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "git_abort_merge",
            "description": "如果处于冲突的 merge 状态，执行 git merge --abort 回滚合并状态。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "git_checkout_file",
            "description": "放弃某些本地未提交文件的更改，将其还原为 HEAD 版本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要还原的文件路径列表"
                    }
                },
                "required": ["file_paths"]
            }
        }
    ]

    initial_log = f"Git pull 输出日志：\nSTDOUT:\n{initial_stdout}\nSTDERR:\n{initial_stderr}\n当前更新源 URL: {source_url}"
    history.append({"role": "user", "content": initial_log})

    success = False
    detail = ""

    for step in range(5):
        logger.info(f"AI 正在思考诊断方案（第 {step + 1} 轮）...")
        try:
            resp = asyncio.run(client.chat(
                history=history,
                system_prompt=system_prompt,
                tools=tools_schema
            ))
        except Exception as e:
            logger.error(f"AI 诊断请求异常: {e}")
            break

        tool_calls = resp.tool_calls or []
        content = resp.content or ""
        if content:
            logger.info(f"AI 提示: {content}")

        history.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls
        })

        if not tool_calls:
            detail = content
            break

        for tc in tool_calls:
            tname = tc.get("function", {}).get("name") or tc.get("name")
            targs = tc.get("function", {}).get("arguments") or tc.get("args") or {}
            if isinstance(targs, str):
                import json
                try:
                    targs = json.loads(targs)
                except Exception:
                    targs = {}

            call_id = tc.get("id", f"call_{tname}_{step}")
            logger.info(f"AI 执行工具调用: {tname}({targs})")

            tool_result = ""
            if tname == "clean_conflicts":
                fps = targs.get("file_paths", [])
                cleaned = []
                for fp in fps:
                    if clean_and_backup_file(fp, backed_up_yamls):
                        cleaned.append(fp)
                tool_result = f"已清理文件: {cleaned}"

            elif tname == "git_pull":
                target_url = targs.get("source_url") or source_url
                code, out, err = run_git_command(["pull", target_url])
                if is_git_pull_success(code, out, err):
                    success = True
                    tool_result = f"Pull 成功！\nSTDOUT: {out}\nSTDERR: {err}"
                else:
                    tool_result = f"Pull 仍有错误或未完成。\nReturncode: {code}\nSTDOUT: {out}\nSTDERR: {err}"

            elif tname == "git_status":
                code, out, err = run_git_command(["status"])
                tool_result = f"Git Status:\n{out}\n{err}"

            elif tname == "git_abort_merge":
                code, out, err = run_git_command(["merge", "--abort"])
                tool_result = f"Git merge --abort 执行完成: {out} {err}"

            elif tname == "git_checkout_file":
                fps = targs.get("file_paths", [])
                code, out, err = run_git_command(["checkout", "--"] + fps)
                tool_result = f"Checkout 结果: {out} {err}"
            else:
                tool_result = f"未知工具: {tname}"

            history.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": str(tool_result)
            })

            if success:
                break

        if success:
            break

    restore_or_merge_yamls(backed_up_yamls, pull_succeeded=success)
    return success, detail


def heuristic_solve_git_update(source_url: str, initial_stdout: str, initial_stderr: str) -> tuple:
    backed_up_yamls = {}
    last_stdout = initial_stdout
    last_stderr = initial_stderr

    for round_idx in range(4):
        logger.info(f"正在使用启发式规则排查更新冲突（第 {round_idx + 1} 轮）...")
        conflict_files = parse_git_conflicts(last_stdout + "\n" + last_stderr)
        if not conflict_files:
            code, status_out, status_err = run_git_command(["status", "--porcelain"])
            for line in status_out.splitlines():
                if line.startswith("UU ") or line.startswith("AA "):
                    conflict_files.append(line[3:].strip())

        if not conflict_files:
            logger.info("未识别出具体冲突文件，尝试直接重新拉取...")
            code, out, err = run_git_command(["pull", source_url])
            last_stdout, last_stderr = out, err
            if is_git_pull_success(code, out, err):
                restore_or_merge_yamls(backed_up_yamls, pull_succeeded=True)
                return True, "拉取成功"
            break

        logger.warning(f"检测到以下引起冲突的文件/目录: {conflict_files}")
        for cf in conflict_files:
            clean_and_backup_file(cf, backed_up_yamls)

        code, out, err = run_git_command(["pull", source_url])
        last_stdout, last_stderr = out, err
        if is_git_pull_success(code, out, err):
            logger.info("清理冲突后重新拉取成功！")
            restore_or_merge_yamls(backed_up_yamls, pull_succeeded=True)
            return True, "拉取成功"

    code, out, err = run_git_command(["pull", source_url])
    final_success = is_git_pull_success(code, out, err)
    restore_or_merge_yamls(backed_up_yamls, pull_succeeded=final_success)
    detail = (out + "\n" + err).strip()
    return final_success, detail


def execute_smart_update(source_idx: int = 0, non_interactive: bool = False) -> tuple:
    if source_idx < 0 or source_idx >= len(SOURCES):
        source_idx = 0
    source_url = SOURCES[source_idx]

    logger.info(f"开始从源 [{source_idx}] {source_url} 拉取更新...")
    code, stdout, stderr = run_git_command(["pull", source_url])

    logger.info(stdout)
    if stderr:
        logger.warning(stderr)

    if is_git_up_to_date(stdout, stderr):
        print_result_banner("UP_TO_DATE")
        return "UP_TO_DATE", "当前已经是最新版本，无需更新。"

    if is_git_pull_success(code, stdout, stderr):
        print_result_banner("SUCCESS")
        return "SUCCESS", "更新成功，已拉取到最新代码。"

    logger.warning("首轮 git pull 未直接成功，正在启动智能冲突处理机制...")

    if is_ai_configured():
        logger.info("检测到 MaiReply 已配置可用 AI 大模型，优先交由 AI 自主分析与解决 Git 冲突...")
        try:
            ai_success, detail = ai_solve_git_update(source_url, stdout, stderr)
            if ai_success:
                print_result_banner("SUCCESS")
                return "SUCCESS", "AI 成功协助解决更新冲突并拉取到最新版本。"
            else:
                logger.warning(f"AI 处理未完全成功 ({detail})，将自动回退到规则启发式处理...")
        except Exception as e:
            logger.error(f"AI 处理过程发生异常: {e}，回退到规则启发式处理...")

    heur_success, detail = heuristic_solve_git_update(source_url, stdout, stderr)
    if heur_success:
        print_result_banner("SUCCESS")
        return "SUCCESS", "通过冲突文件自动清理与配置合并，已成功更新至最新代码。"
    else:
        print_result_banner("FAILED", detail)
        return "FAILED", f"未能自动解决冲突更新失败: {detail}"


def restart_bot_process():
    logger.info("准备重启 Bot 进程以使新代码生效...")
    bat_path = os.path.abspath("启动脚本.bat")
    try:
        if os.path.exists(bat_path):
            subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, "main.py"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        logger.error(f"拉起新 Bot 进程异常: {e}")

    time.sleep(1.5)
    os._exit(0)


async def admin_update_system(bot, event, config):
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        master_id = ym.common_config.basic_config.get("master", {}).get("id")
    except Exception:
        master_id = None

    sender_id = getattr(event, "user_id", None)
    if master_id and sender_id and int(sender_id) != int(master_id):
        await bot.send(event, "抱歉，系统更新功能仅限 Bot 管理员执行！")
        return

    source_idx = 0
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        ym = YAMLManager.get_instance()
        source_idx = int(ym.common_config.basic_config.get("git_update_source", 0))
    except Exception:
        source_idx = 0

    await bot.send(event, f"收到更新指令！已启动后台智能更新流程（使用源序号: {source_idx}）...\n完成后将通过私信向您汇报结果并自动重启。")

    async def _bg_update_task():
        try:
            status, detail = await asyncio.to_thread(execute_smart_update, source_idx, True)
            if status in ["UP_TO_DATE", "SUCCESS"]:
                report_msg = (
                    f"【系统更新报告】\n"
                    f"状态: {'已经是最新版本' if status == 'UP_TO_DATE' else '更新成功'}\n"
                    f"详情: {detail}\n"
                    f"Bot 将在 3 秒后自动重启以载入新模块..."
                )
            else:
                report_msg = (
                    f"【系统更新报告】\n"
                    f"状态: 更新失败\n"
                    f"详情: {detail}\n"
                    f"配置文件已安全保护，请根据日志排查。"
                )

            if master_id:
                try:
                    await bot.send_friend_message(int(master_id), report_msg)
                except Exception as e:
                    logger.error(f"向管理员发送更新报告私信失败: {e}")
                    try:
                        await bot.send(event, report_msg)
                    except Exception:
                        pass

            if status in ["UP_TO_DATE", "SUCCESS"]:
                await asyncio.sleep(2)
                restart_bot_process()
        except Exception as e:
            logger.error(f"后台更新任务异常: {e}")
            if master_id:
                try:
                    await bot.send_friend_message(int(master_id), f"系统更新发生严重异常: {e}")
                except Exception:
                    pass

    asyncio.create_task(_bg_update_task())


def updaat(f=False, source=None, yamls: dict = None):
    sources = SOURCES
    if source is None:
        for i in sources:
            logger.info(f"{sources.index(i)}. {i}")
        logger.info("拉取bot代码\n--------------------")
        logger.warning("0为git源,1为gitcode源，其他镜像源可能存在版本滞后现象。如拉取失败可自行为environments/MinGit/cmd/git.exe配置代理(windows)。")
        source = input("选择更新源(输入数字 )：").strip()

    try:
        source_idx = int(source)
    except Exception:
        logger.error("无效输入，重新执行")
        return updaat(f, None, yamls)

    if source_idx < 0 or source_idx >= len(sources):
        logger.error("无效输入，重新执行")
        return updaat(f, None, yamls)

    execute_smart_update(source_idx=source_idx, non_interactive=False)

def fuck_requirements():
    from ruamel.yaml import YAML

    yaml = YAML(typ='safe')
    with open('data/system/requirements.yaml', 'r', encoding='utf-8') as f:
        local_config = yaml.load(f)
    update_requirements = local_config.get("update")
    for i in update_requirements:
        try:
            logger.info(f"开始更新依赖{i}...")
            pip_main(['install', '--upgrade', i])
        except Exception as e:
            logger.error(f"更新依赖{i}失败：{e}")
    for i in local_config.get("restrict"):
        try:
            logger.info(f"开始安装依赖{i}...")
            pip_main(['install', i])
        except Exception as e:
            logger.error(f"安装依赖{i}失败：{e}")


def parse_requirements(file_path):
    """
    解析 requirements.txt 文件，返回包名和版本需求信息。
    """
    requirements = {}
    requirement_pattern = re.compile(r'([a-zA-Z0-9_.-]+)([<>=!~].*)?')
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):  # 跳过空行和注释
                continue
            match = requirement_pattern.match(line)
            if match:
                pkg = match.group(1).lower()  # 包名
                spec = match.group(2)  # 版本约束
                requirements[pkg] = spec.strip() if spec else None
            else:
                print(f"无法解析行：'{line}'，请检查格式是否正确。")
    return requirements


def get_installed_packages():
    """
    使用 pip 获取已安装的包和版本信息。
    """

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'freeze'],  # 避免找不到 pip
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    installed_packages = {}
    logger.info(f"获取已安装包中...")
    logger.info(f"{result.stdout}")
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if '==' in line:
                pkg, version = line.split('==')
                installed_packages[pkg.strip()] = version.strip()
    else:
        print(f"获取已安装包失败：{result.stderr}")
    return installed_packages


def check_requirements(requirements_file):
    """
    检查 requirements.txt 中的依赖是否已安装。
    """
    if not os.path.exists(requirements_file):
        print(f"文件 {requirements_file} 不存在！")
        return

    requirements = parse_requirements(requirements_file)

    installed_packages = get_installed_packages()

    normalize_package_name = lambda name:name.lower().replace('_', '-')
    installed_packages = {normalize_package_name(k): v for k, v in installed_packages.items()}
    requirements = {normalize_package_name(k): v for k, v in requirements.items()}

    missing = []
    mismatched = []

    for pkg, required_version in requirements.items():
        if pkg not in installed_packages:
            missing.append(pkg)
        elif required_version and installed_packages[pkg] != required_version:
            mismatched.append((pkg, required_version, installed_packages[pkg]))

    if missing:
        print("缺失的包：")
        for pkg in missing:
            print(f"  - {pkg}")
            if "<" in pkg or ">" in pkg or "=" in pkg:
                pip_main(['install', pkg])
            else:
                pip_main(['install', '--upgrade', pkg])

    if mismatched:
        print("\n版本不匹配的包(一般不用管这个)：")
        for pkg, required_version, installed_version in mismatched:
            print(f"  - {pkg}: 需要 {required_version}, 已安装 {installed_version}")

    if not missing and not mismatched:
        print("所有依赖都已正确安装！")


def extract_cuda_version(nvcc_output):
    """
    从nvcc --version命令的输出中提取CUDA版本，并转换为用于构建PyTorch URL的形式。
    :param nvcc_output: str, nvcc --version命令的输出字符串。
    :return: str, 转换后的CUDA版本号，如'cu121'。
    """
    match = re.search(r'release (\d+\.\d+)', nvcc_output)
    if match:
        cuda_version = match.group(1)  # 获取主版本和次版本号
        major, minor = cuda_version.split('.')
        return f'cu{major}{minor}'
    else:
        return None


def ai_req():
    try:
        nvcc_output = subprocess.check_output(["nvcc", "--version"], stderr=subprocess.STDOUT).decode()
        cuda_torch_suffix = extract_cuda_version(nvcc_output)
        if cuda_torch_suffix:
            logger.info(f"检测到CUDA版本：{cuda_torch_suffix[2:]}，正在安装支持CUDA的PyTorch...")
        else:
            logger.warning("未能检测到CUDA版本，假设系统中未安装CUDA。")
    except Exception:
        logger.error('CUDA')
        logger.warning("未能检测到CUDA版本或nvcc未安装，假设系统中未安装CUDA。")
        cuda_torch_suffix = None

    try:
        pip_main(['install', 'opencv-python-headless'])
        if cuda_torch_suffix:
            # 如果检测到了支持的CUDA版本，则安装带有CUDA支持的PyTorch包
            pip_main(['install', 'torch', 'torchvision', 'torchaudio',
                      f'--index-url=https://download.pytorch.org/whl/{cuda_torch_suffix}'])
        else:
            # 如果没有检测到CUDA或不支持的CUDA版本，则安装CPU-only版本的PyTorch包
            logger.info("未检测到CUDA或CUDA版本不受支持，正在安装仅CPU版本的PyTorch...")
            pip_main(['install', 'opencv-python-headless', 'torch', 'torchvision', 'torchaudio'])
    except subprocess.CalledProcessError as e:
        logger.error(f"安装PyTorch时出错：{e}")
        sys.exit(1)

    logger.info("ai相关库安装成功完成")
    return
def export_yaml(base_dir="run"):
    if not os.path.exists("old_yamls"):
        os.mkdir("old_yamls")
    """
    导出yaml文件到old_yamls文件夹
    """

    yaml_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yaml"):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, base_dir)
                yaml_files.append(relative_path)
    def copy_to_old_yamls(yaml_files, target_dir="old_yamls"):
        for rel_path in yaml_files:
            src_path = os.path.join(base_dir, rel_path)
            dst_path = os.path.join(target_dir, rel_path)

            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            print(f"Copied: {src_path} -> {dst_path}")

    copy_to_old_yamls(yaml_files)
    logger.info("导出yaml文件到old_yamls文件夹完成")
    logger.info("请将old_yamls文件夹复制到新的Eridanus目录下，放在run目录旁边。路径应当为：Eridanus/old_yamls")
    logger.info("在新目录下运行Eridanus/tool.py或更新脚本，选择导入旧配置即可。")
    return yaml_files
def import_yaml(base_dir="run"):
    yaml_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yaml"):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, base_dir)
                yaml_files.append(relative_path)
    failed_files = []
    for files in yaml_files:
        if os.path.exists(os.path.join(base_dir, files)):
            logger.warning(f"开始处理冲突文件{files}...")
            try:
                conflict_file_dealter(os.path.join("old_yamls", files), os.path.join(base_dir, files))
            except Exception as e:
                logger.error(f"处理冲突文件{files}失败：{e}")
                continue
        else:
            logger.warning(f"文件{files}在新配置中不存在，跳过")
            continue
    if failed_files:
        logger.warning(f"以下文件处理失败：{failed_files}，建议手动处理")
async def main():
    setup_git_proxy_if_interactive()
    logger.info("""请输入要执行的指令：
        [1].youtube登录
        [2].更新bot代码(常用)
        [3].playwright工具安装
        [4].开发者工具
        [5].若只的检测相关ai库(如奶龙检测)
        [6].B站 or 抖音 or 小红书 登录。不登也不影响你用
        [7].导出配置文件
        [8].导入配置文件
        [9].更新jmcomic库(当代理正常但jm功能不可用时请自助更新)
        [10].退出""")
    user_input = input("请输入指令序号：").strip()
    if user_input == "1":
        logger.info("youtube登录")
        logger.warning(
            """
            \n
            youtube登录需要手动操作，请按照以下步骤进行：
            0.等待链接出现
            1.打开链接
            2.输入input code 后面的代码
            3.继续使用你的google账号登录
            4.完成后，在这个页面按回车(等待结束后自动退出)
            """
        )
        from framework_common.framework_util.yamlLoader import YAMLManager

        yamlmanager = YAMLManager.get_instance()
        proxy = yamlmanager.common_config.basic_config.get("proxy", {}).get("http_proxy")
        pyproxies = {
            "http": proxy,
            "https": proxy
        }

        from pytubefix import YouTube
        from pytubefix.helpers import reset_cache
        reset_cache()

        yt = YouTube(url="https://www.youtube.com/watch?v=PZnXXFrjSjg", client='IOS', proxies=pyproxies, use_oauth=True,
                     allow_oauth_cache=True)
        ys = yt.streams.get_audio_only()
    elif user_input == "2":
        updaat()
    elif user_input == "3":
        logger.info("playwright工具安装(b站动态爬取需要)")
        os.system(f"\"{python_path}\" -m playwright install chromium")
    elif user_input == "4":
        logger.info("""请输入开发者工具序号：
#
        2 没想好呢""")
        input("请输入开发者工具序号：")
    elif user_input == "5":
        logger.info("安装奶龙相关ai库依赖中")
        ai_req()
    elif user_input == "6":
        install_and_import("PyExecJS")
        install_and_import("PyGObject", "gi")

        from run.streaming_media.service.Link_parsing.core.login_core import login_core_select
        await login_core_select()
    elif user_input == "7":
        logger.info("导出配置文件")
        export_yaml()
        logger.info("配置文件导出完成")
        logger.warning("请将old_yamls文件夹复制到新的Eridanus目录下。如有必要，请自行覆盖新的data文件夹")
    elif user_input == "8":
        logger.info("导入配置文件")
        import_yaml()
        logger.info("配置文件导入完成")
    elif user_input == "9":
        if pip_main is not None:
            pip_main(['install', '--upgrade', 'jmcomic'])
    elif user_input == "10":
        logger.info("退出")

if __name__ == '__main__':
    asyncio.run(main())
