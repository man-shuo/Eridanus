import importlib.util
import os
import re
import subprocess
import sys
from urllib.parse import urlparse
from developTools.utils.logger import get_logger
from pip._internal.cli.main import main as pip_main
logger = get_logger()

DEFAULT_PYPI_SOURCE = "https://mirrors.aliyun.com/pypi/simple/"


def get_pypi_source() -> str:
    """获取 basic_config.yaml 中配置的 PyPI 源，默认阿里源"""
    # 1. 优先尝试从已初始化的 YAMLManager 获取
    try:
        from framework_common.framework_util.yamlLoader import YAMLManager
        if YAMLManager._instance is not None and hasattr(YAMLManager._instance, 'common_config'):
            basic_cfg = getattr(YAMLManager._instance.common_config, 'basic_config', None)
            if isinstance(basic_cfg, dict):
                src = basic_cfg.get("pypi_source") or basic_cfg.get("pip_source")
                if src:
                    return str(src).strip()
    except Exception:
        pass

    # 2. 直接从 basic_config.yaml 文件读取（支持早于 YAMLManager 初始化前使用，避免启动时循环依赖）
    candidate_paths = [
        os.path.join(os.getcwd(), "run", "common_config", "basic_config.yaml"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "run", "common_config", "basic_config.yaml")),
    ]
    for cfg_path in candidate_paths:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
                match = re.search(r'^\s*(?:pypi_source|pip_source)\s*:\s*["\']?([^"\'\r\n#]+)', file_content, re.MULTILINE)
                if match:
                    src = match.group(1).strip()
                    if src:
                        return src
            except Exception:
                pass

    return DEFAULT_PYPI_SOURCE
pypi_source = get_pypi_source()
pip_main(['config', 'set', 'global.index-url', pypi_source])
def install_and_import(package_name, import_name=None):
    """检测模块是否已安装，若未安装则通过 pip 安装"""
    if import_name is None:
        import_name = package_name

    spec = importlib.util.find_spec(import_name)

    if spec is None:
        logger.warning(f"{package_name} 未安装，正在安装...")
        pip_main(['install', package_name])
        spec = importlib.util.find_spec(import_name)
        if spec is None:
            logger.error(f"安装失败：无法找到 {import_name} 模块")
            return None

    return importlib.import_module(import_name)
