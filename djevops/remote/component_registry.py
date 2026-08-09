from djevops.remote.scaffold import load_components, save_components

class ComponentRegistry:

    def __init__(self, log):
        self._log = log
        self._required = set()

    def require(self, component):
        key = _get_full_key(component)
        self._required.add(key)
        components = load_components()
        hash_ = component.calculate_hash()
        stored_hash = components.get(key, {}).get('hash')
        if hash_ == stored_hash:
            return False
        self._log(f'Installing {component}...')
        component.install()
        components[key] = {'component': component, 'hash': hash_}
        save_components(components)
        return True

    def uninstall_unused(self):
        components = load_components()
        uninstalled = []
        for key in reversed(list(components)):
            if key in self._required:
                continue
            component = components[key]['component']
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
