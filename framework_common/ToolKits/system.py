from .base import BaseTool
from framework_common.utils.install_and_import import install_and_import as _install_and_import


class SystemProcessor(BaseTool):
    def __init__(self):
        super().__init__(__class__.__name__)

    def install_and_import(self, package_name, import_name=None):
        """检测模块是否已安装，若未安装则通过统一配置的 pip 源安装并导入"""
        return _install_and_import(package_name, import_name)
