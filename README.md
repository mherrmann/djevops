# djevops: Host Django on bare metal

djevops is a command-line tool for deploying Django web apps to Linux VPSs.
Unlike other tools, djevops runs Django "on bare metal". That is, without
Docker. This makes development faster and easier.

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
constants in file `djevops/secrets.py`.

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

djevops uses [Litestream](https://litestream.io/) for SQLite backups. Litestream
can store backups in S3, Azure Blob Storage and many others. The keys you add to
the `backup` element above get copied into a `replica` element in Litestream's
config. For more information about the available options, please
see [Litestream's documentation](https://litestream.io/reference/config/).
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
to Git. djevops lets you specify such values in the file `djevops/secrets.py`,
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

## Development

Install the `test` dependencies from
[`djevops/pyproject.toml`](djevops/pyproject.toml). The easiest way I know for
doing this is with [`uv`](https://docs.astral.sh/uv/):

```
# Need to cd into the subdirectory because pyproject.toml doesn't lie at the
# project root.
cd djevops
uv venv
source .venv/bin/activate
uv sync --no-install-project --extra test
cd ..
```

Then, you can do `python -m unittest` to run tests. This requires some API keys
and environment variables.
