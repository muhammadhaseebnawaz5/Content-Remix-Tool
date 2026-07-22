"""
PluginManager - Dynamically loads plugins from the plugins/ folder.
Future extensibility for third-party effects.
"""

import os
import sys
import importlib.util
from typing import List, Dict, Any, Optional


class PluginManager:
    """Manages plugin discovery and loading."""

    def __init__(self, plugins_dir: Optional[str] = None):
        if plugins_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            plugins_dir = os.path.join(base_dir, "plugins")
        self._plugins_dir = plugins_dir
        self._plugins: Dict[str, Any] = {}

    def discover(self) -> List[str]:
        """Discover available plugin modules."""
        if not os.path.exists(self._plugins_dir):
            return []
        plugins = []
        for item in os.listdir(self._plugins_dir):
            if item.endswith(".py") and not item.startswith("_"):
                plugins.append(item[:-3])
            elif os.path.isdir(os.path.join(self._plugins_dir, item)):
                init_file = os.path.join(self._plugins_dir, item, "__init__.py")
                if os.path.exists(init_file):
                    plugins.append(item)
        return plugins

    def load(self, name: str) -> Optional[Any]:
        """Load a plugin by name."""
        plugin_path = os.path.join(self._plugins_dir, f"{name}.py")
        if not os.path.exists(plugin_path):
            plugin_path = os.path.join(self._plugins_dir, name, "__init__.py")
        if not os.path.exists(plugin_path):
            return None

        try:
            spec = importlib.util.spec_from_file_location(name, plugin_path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self._plugins[name] = module
            return module
        except Exception as e:
            print(f"Failed to load plugin {name}: {e}")
            return None

    def load_all(self) -> Dict[str, Any]:
        """Load all discovered plugins."""
        for name in self.discover():
            self.load(name)
        return self._plugins

    def get(self, name: str) -> Optional[Any]:
        """Get loaded plugin."""
        return self._plugins.get(name)

    def list_plugins(self) -> List[str]:
        """List loaded plugin names."""
        return list(self._plugins.keys())
