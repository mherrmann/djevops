from djevops.config import get_services_users_envs, DEFAULT_ENV
from unittest import TestCase


class GetServicesUsersEnvsTest(TestCase):

    def test_single_service(self):
        self._check(
            {'services': {'web': {'type': 'django'}}},
            {'web': ('web', {})}
        )

    def test_clear_env(self):
        self._check(
            {
                'services': {
                    'web': {
                        'type': 'django',
                        'env': {'clear': {'DEBUG': 'False'}}
                    }
                }
            },
            {'web': ('web', {'DEBUG': 'False'})}
        )

    def test_secret_env(self):
        self._check(
            {
                'services': {
                    'web': {
                        'type': 'django',
                        'env': {'secret': ['API_KEY']}
                    }
                }
            },
            {'web': ('web', {'API_KEY': 'secret123'})},
            secrets={'API_KEY': 'secret123'}
        )

    def test_inherit_env(self):
        self._check(
            {
                'services': {
                    'web': {
                        'type': 'django',
                        'env': {'clear': {'DEBUG': 'False'}}
                    },
                    'celery': {
                        'type': 'celery',
                        'env': {'inherit': 'web'}
                    }
                }
            },
            {
                'web': ('web', {'DEBUG': 'False'}),
                'celery': ('web', {'DEBUG': 'False'})
            }
        )

    def test_inherit_processed_after_parent(self):
        self._check(
            {
                'services': {
                    'celery': {
                        'type': 'celery',
                        'env': {'inherit': 'web'}
                    },
                    'web': {
                        'type': 'django',
                        'env': {'clear': {'DEBUG': 'False'}}
                    }
                }
            },
            {
                'web': ('web', {'DEBUG': 'False'}),
                'celery': ('web', {'DEBUG': 'False'})
            }
        )

    def _check(self, config, expected, secrets=None):
        expected_with_defaults = {
            name: (user, {**DEFAULT_ENV, **env})
            for name, (user, env) in expected.items()
        }
        self.assertEqual(
            expected_with_defaults,
            get_services_users_envs(config, secrets or {})
        )
