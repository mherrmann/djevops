from django.conf import settings
from getpass import getuser
from pathlib import Path

import os
import sys

def main():
    check_gunicorn()
    check_databases()
    check_staticfiles()
    check_allowed_hosts()
    check_celery()

def check_gunicorn():
    try:
        import gunicorn
    except ImportError:
        error("Please add `gunicorn` to your requirements.txt file.")

def check_databases():
    for alias, config in getattr(settings, 'DATABASES', {}).items():
        if config['ENGINE'] != 'django.db.backends.sqlite3':
            error(
                'Only ENGINE django.db.backends.sqlite3 is supported in '
                'setting DATABASES.'
            )

        db_path = Path(config['NAME'])
        if not db_path.is_absolute():
            base_dir = getattr(settings, 'BASE_DIR', Path.cwd())
            db_path = base_dir / db_path

        if not is_writeable(db_path):
            error(
                f"SQLite database file {db_path} is not writeable by user "
                f"{getuser()}. Please set Django setting "
                f"DATABASES['{alias}']['NAME'] to a writeable path. A good "
                f"expression is:\n"
                f"    os.getenv('SQLITE_DB_FILE') or <what you had before>\n"
                f"(Don't forget to `import os`.)"
            )

def check_staticfiles():
    if 'django.contrib.staticfiles' in settings.INSTALLED_APPS:
        if not settings.STATIC_ROOT:
            error(
                "Please set Django setting STATIC_ROOT to a directory. A good "
                "expression is:\n"
                "    STATIC_ROOT = os.getenv('STATIC_ROOT')"
            )

def check_allowed_hosts():
    host_name = os.environ['HOST_NAME']
    if host_name not in settings.ALLOWED_HOSTS:
        error(
            "Please add the value of environment variable HOST_NAME to Django "
            "setting ALLOWED_HOSTS. For example:\n"
            "    ALLOWED_HOSTS = []\n"
            "    if os.getenv('HOST_NAME'):\n"
            "        ALLOWED_HOSTS.append(os.getenv('HOST_NAME'))"
        )

def check_celery():
    try:
        import celery
    except ImportError:
        # Doesn't use Celery, so no need to check its configuration.
        return
    if getattr(settings, 'CELERY_BROKER_URL') != 'redis://localhost':
        error(
            "Please set Django setting CELERY_BROKER_URL to redis://localhost. "
            "If you have a different BROKER_URL setting, please change your "
            "Celery app's namespace to CELERY."
        )

def is_writeable(path: Path):
    if path.exists():
        return os.access(path, os.W_OK)
    else:
        try:
            path.touch()
        except PermissionError:
            return False
        else:
            path.unlink()
            return True

def error(message):
    print(message)
    sys.exit(1)
