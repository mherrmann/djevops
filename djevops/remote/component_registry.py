from djevops.remote.components import Component
from djevops.remote.scaffold import load_components, save_components

class ComponentRegistry:

    def __init__(self, log):
        self._log = log
        self._required = set()

    def require(self, component):
        key = _get_full_key(component)
        self._required.add(key)
        components = load_components()
        if components.get(key) == component.args:
            return False
        self._log(f'Installing {component}...')
        component.install()
        components[key] = component.args
        save_components(components)
        return True

    def uninstall_unused(self):
        components = load_components()
        uninstalled = []
        for key in reversed(list(components)):
            if key in self._required:
                continue
            component = _restore(key, components[key])
            self._log(f'Uninstalling {component}...')
            component.uninstall()
            del components[key]
            uninstalled.append(component)
            # Persist after each removal so an aborted run doesn't leave the
            # file claiming an already-uninstalled component is still present.
            save_components(components)
        return uninstalled

def _get_full_key(component):
    result = type(component).__name__
    if component.key is not None:
        result += f':{component.key}'
    return result

def _restore(full_key, args):
    class_name = full_key.split(':', 1)[0]
    classes = {cls.__name__: cls for cls in Component.__subclasses__()}
    return classes[class_name](**args)
