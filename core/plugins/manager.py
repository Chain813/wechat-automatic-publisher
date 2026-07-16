import os
import importlib
import inspect
from typing import Dict
from core.plugins.base import BaseSourcePlugin
from loguru import logger

class PluginManager:
    """
    插件管理器：动态加载 core/plugins 下的所有 BaseSourcePlugin 子类
    """
    def __init__(self):
        self.plugins: Dict[str, BaseSourcePlugin] = {}
        self._load_all_plugins()

    def _load_all_plugins(self):
        plugins_dir = os.path.dirname(__file__)
        # 遍历 core/plugins 及其子目录
        for root, dirs, files in os.walk(plugins_dir):
            for file in files:
                if file.endswith('.py') and not file.startswith('__') and file != 'base.py' and file != 'manager.py':
                    rel_path = os.path.relpath(os.path.join(root, file), plugins_dir)
                    module_name = f"core.plugins.{rel_path[:-3].replace(os.sep, '.')}"
                    self._import_plugin_module(module_name)

    def _import_plugin_module(self, module_name: str):
        try:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, BaseSourcePlugin) and obj != BaseSourcePlugin:
                    plugin_instance = obj()
                    self.plugins[plugin_instance.source_id] = plugin_instance
                    logger.debug(f"加载插件成功: {plugin_instance.display_name} ({plugin_instance.source_id})")
        except Exception as e:
            logger.error(f"加载插件模块 {module_name} 失败: {e}")

    def get_plugin(self, source_id: str) -> BaseSourcePlugin:
        return self.plugins.get(source_id)

    def get_all_plugins(self) -> Dict[str, BaseSourcePlugin]:
        return self.plugins

plugin_manager = PluginManager()
