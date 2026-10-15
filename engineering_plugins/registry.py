"""Discover versioned plugins; orchestration never branches on framework names."""
from functools import lru_cache
from importlib import import_module
import pkgutil
import engineering_plugins


@lru_cache(maxsize=1)
def plugins():
    items = []
    ids = set()
    for module in pkgutil.iter_modules(engineering_plugins.__path__):
        if module.name.startswith('_') or module.name in ('registry', 'support'):
            continue
        plugin = import_module('engineering_plugins.' + module.name)
        manifest = getattr(plugin, 'MANIFEST', None)
        if not manifest:
            continue
        if manifest.get('api_version') != '1.0' or not all(callable(getattr(plugin, n, None)) for n in ('detect', 'verification')):
            raise RuntimeError('Invalid engineering plugin: ' + module.name)
        if manifest['id'] in ids:
            raise RuntimeError('Duplicate plugin: ' + manifest['id'])
        ids.add(manifest['id']); items.append(plugin)
    return tuple(sorted(items, key=lambda p: (-p.MANIFEST.get('priority', 0), p.MANIFEST['id'])))


def by_id(plugin_id):
    return next((p for p in plugins() if p.MANIFEST['id'] == plugin_id), None)


def for_type(project_type):
    return next((p for p in plugins() if project_type in p.MANIFEST['project_types']), None)


def detect(root):
    for plugin in plugins():
        if plugin.detect(root):
            return dict(plugin.verification(root), type=plugin.MANIFEST['project_types'][0], plugin_id=plugin.MANIFEST['id'])
    return {'type': 'unknown', 'commands': [], 'plugin_id': ''}
