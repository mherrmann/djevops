# djevops: Self-host Django easily

djevops is a command-line tool for deploying your Django web app to a Linux VPS.
It runs and manages all necessary components (database, Redis, etc.) on your
server.

Unlike other tools, djevops does not use Docker. This makes it possible to "push
to prod" in seconds. Compared to Ansible, djevops' specialization on Django lets
you write significantly less code. The flip side is that djevops is less
general.

To get started with djevops, all you need is SSH root access to a Linux VPS
running Ubuntu or Debian. Install djevops on your local machine with
`pip install djevops`. Then, execute `djevops init` in your Django app's Git
repository. You get a config file that looks similar to the following:

```
server: 1.2.3.4

git:
  repo: githubuser/reponame
  branch: main

services:
  web:
    type: django
    env:
      clear:
        ALLOWED_HOSTS: your.website.com
      secret:
        - DJANGO_SECRET_KEY

db:
  type: sqlite

mail:
  host: smtp.gmail.com
  user: SMTP_USER
  password: SMTP_PASSWORD
```

Secrets such as `DJANGO_SECRET_KEY` or `SMTP_PASSWORD` can be specified as
constants in file `deploy/secrets.py`.

Most config values are optional. Fill in the ones you want and run
`djevops deploy`. djevops then clones your Git repo on the `server` and starts
all services. As you work on your Django app and push new commits to Git, simply
run `djevops deploy` again to apply them to your server.

## Features

<details>
<summary>Automatic SSL certificates</summary>

djevops generates and automatically renews SSL certificates for any domains you
specify in Django setting `ALLOWED_HOSTS`. The domains need to be tied to your
server's IP address.
</details>

<details>
<summary>Error emails</summary>

If you filled in the `mail` section in the config file, then you can make Django
email you when errors occur. To do so, set `ADMINS` in Django's `settings.py` as
follows:

```
ADMINS = [('Your Name', 'your@email.com)]
```

Error emails require Django setting `DEBUG` to be `False`.
</details>

<details>
<summary>Automatic database backups</summary>

You can set up automatic database backups by adding a `backup` element to the
`db` section in the djevops config file. For example:

```
db:
  type: sqlite
  backup:
    type: s3
    bucket: mybackup
    access-key-id: S3_BACKUP_ACCESS_KEY
    secret-access-key: S3_BACKUP_SECRET_KEY
    path: db
    region: us-east-1
```

Backups are created continuously while your server is running. If you ever
re-install your server, then the latest backup is automatically restored.

For database type `sqlite`, djevops uses [Litestream](https://litestream.io/)
for backups. Litestream can store backups in S3, Azure Blob Storage and many
others. The keys you add to the `backup` element above get copied into a
`replica` element in Litestream's config. For more information about the
available options, please
see [Litestream's documentation](https://litestream.io/reference/config/).

Djevops also supports database type `postgres`. For more information about this,
please see below.
</details>

<details>
<summary>PostgreSQL</summary>

Instead of SQLite, you can use PostgreSQL by setting the database `type` to
`postgres`:

```
db:
  type: postgres
```

You then configure the connection yourself in your `settings.py`:

```
import os

DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'myapp',
    'USER': 'myapp',
    'PASSWORD': os.environ['DB_PASSWORD'],
    'HOST': 'localhost'
}
```

djevops reads these settings and installs PostgreSQL on the server, creating the
database and user with the password you specified. Keep the password out of Git
by storing it in `deploy/secrets.py`. For example:

```
DB_PASSWORD = "<some strong password>"
```

Then reference it as a `secret` in the Django service's environment:

```
services:
  web:
    type: django
    env:
      secret:
        - DB_PASSWORD
```

You also need to add `psycopg[binary]` to your `pyproject.toml` or
`requirements.txt` file.

As with SQLite, you can add a `backup` element to enable automatic backups. By
default, PostgreSQL backups are taken once per day. You can customize this by
setting `sync-interval` in the `backup` element, for example to `1h` for hourly
backups.
</details>

<details>
<summary>Background tasks via Celery and Redis</summary>

If your Django app uses the `celery` Python package, then you can add a Celery
worker by adding the following item to the djevops config:

```
services:
  web:
    # as before
  celery:
    type: celery
    env:
      inherit: web
```

To install Redis on the server (which many Django apps use as Celery's backend),
add an empty `redis` block:

```
redis:
```

This setup lets you run Python functions asynchronously and on a schedule such
as "every five hours". The service of type `celery` also runs the necessary
`beat` scheduler.
</details>

<details>
<summary>Easy access to log files</summary>

djevops writes the log file for each service to `/var/log/<service>.log`. To
read it, simply SSH into the server and do `less`, `tail -f`, etc. To prevent
log files from filling up your server's disk space, djevops also rotates and
compresses log files.
</details>

<details>
<summary>Secret handling</summary>

Very often, you have secrets that you need on the server but should not commit
to Git. djevops lets you specify such values in the file `deploy/secrets.py`,
and refer to them from your config file. The way this works is that `secrets.py`
gets executed on your local machine, and the produced values then get uploaded
as constants to the server. This gives you a lot of flexibility. You can
hardcode values in `secrets.py` and not commit that file to Git. Or you can for
example make `secrets.py` read from environment variables that are available
when you do `djevops deploy`:

```
import os
MY_SECRET = os.environ['MY_SECRET']
```

You can also invoke password managers in `secrets.py`, etc.
</details>

<details>
<summary>Secure defaults</summary>

djevops uses secure defaults whenever possible. For example, each `service` runs
as a separate user. This means that environment variables cannot leak from one
service to another. djevops also makes sure that no unintended ports are open,
such as for example port 25 when using Postfix for sending emails.
</details>

<details>
<summary>Automatic OS updates</summary>

djevops sets up automatic OS updates to keep your server up-to-date and secure.
This does not apply major version upgrades, which could introduce potentially
breaking changes.
</details>

<details>
<summary>Easy access to `manage.py shell` on the server</summary>

Just type `djevops shell` to be dropped into a remote Django shell on your
server. This uses the environment variables and user of the first service of
type `django` in `deploy/djevops.yml`.
</details>

## Development

Install the `test` dependencies from `pyproject.toml`. The easiest way I know
for doing this is with [`uv`](https://docs.astral.sh/uv/):

```
uv venv
source .venv/bin/activate
uv sync --no-install-project --extra test
```

Then, you can do `python -m unittest` to run tests. This requires several API
keys specified in environment variables.
