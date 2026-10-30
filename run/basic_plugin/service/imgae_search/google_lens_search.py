import asyncio
import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional

logger = logging.getLogger('google_lens_search')

DEFAULT_LENS_BIN_PATHS = [
    os.path.join(os.path.dirname(__file__), 'google_lens_search', 'bin', 'fish.mjs'),
    os.path.join(os.path.dirname(__file__), 'google_lens_search', 'bin', 'lens.mjs'),
    os.path.join(os.path.dirname(__file__), 'fish_find_chicken', 'bin', 'fish.mjs'),
    r'C:\Users\Administrator\Downloads\鱼鱼找鸡-插件-v1.0.0\鱼鱼找鸡-1.0.0\bin\fish.mjs',
]

def find_lens_script_path() -> Optional[str]:
    custom_path = os.environ.get('GOOGLE_LENS_SEARCH_PATH') or os.environ.get('FISH_FIND_CHICKEN_PATH')
    if custom_path and os.path.exists(custom_path):
        return os.path.abspath(custom_path)
    for p in DEFAULT_LENS_BIN_PATHS:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None

async def search_google_lens(
    image_path: str,
    proxy: Optional[str] = None,
    engines: Optional[str] = None,
    timeout: int = 45,
    strict: bool = True,
    max_accounts: int = 5,
    browser_exe: Optional[str] = None,
) -> Dict[str, Any]:
    if not image_path or not os.path.exists(image_path):
        return {'status': 'error', 'message': f'本地图片不存在: {image_path}', 'accounts': []}

    lens_bin = find_lens_script_path()
    if not lens_bin:
        return {'status': 'error', 'message': '未找到 Google Lens 检索脚本，请确认安装路径', 'accounts': []}

    node_cmd = shutil.which('node') or 'node'
    cmd = [
        node_cmd,
        lens_bin,
        os.path.abspath(image_path),
        '--json',
        '--max',
        str(max_accounts),
        '--timeout',
        str(timeout),
    ]

    if engines:
        cmd.extend(['--engines', str(engines)])
    if not strict:
        cmd.append('--no-strict')
    if proxy and str(proxy).strip():
        cmd.extend(['--proxy', str(proxy).strip()])
    if browser_exe and os.path.exists(browser_exe):
        cmd.extend(['--browser', os.path.abspath(browser_exe)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 15)
        out_str = stdout.decode('utf-8', errors='replace').strip()
        err_str = stderr.decode('utf-8', errors='replace').strip()

        if proc.returncode != 0 and not out_str:
            logger.warning(f'Google Lens 进程退出码异常 {proc.returncode}: {err_str}')
            return {'status': 'error', 'message': f'Google Lens 检索失败 (code {proc.returncode}): {err_str}', 'accounts': []}

        json_start = out_str.find('{')
        json_end = out_str.rfind('}')
        if json_start != -1 and json_end != -1 and json_end > json_start:
            payload = json.loads(out_str[json_start : json_end + 1])
            accounts = payload.get('accounts', [])
            return {
                'status': 'success',
                'accounts': accounts,
                'text': payload.get('text', ''),
                'engines_used': payload.get('enginesUsed', []),
                'failures': payload.get('failures', []),
                'elapsed_ms': payload.get('elapsedMs', 0),
            }

        return {'status': 'error', 'message': f'解析返回结果失败: {out_str or err_str}', 'accounts': []}

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {'status': 'error', 'message': f'Google Lens 检索超时 ({timeout}s)', 'accounts': []}
    except Exception as e:
        logger.error(f'调用 Google Lens 检索异常: {e}')
        return {'status': 'error', 'message': str(e), 'accounts': []}

search_fish_chicken = search_google_lens
