# djevops: Host Django on bare metal

djevops is a command-line tool for deploying Django web apps to Linux VPSs.
Unlike other tools, djevops runs Django "on bare metal". That is, without
Docker. This makes development faster and easier.

Other features of djevops include:

 * SSL certificate handling and renewals
 * Emails to admins when server errors occur
 * Automatic database backups
 * Built-in support for Celery and Redis
 * Easy access to log files
 * Secret handling
 * Secure defaults
 * Automatic OS updates

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
  celery:
    type: celery
    env:
      inherit: web

db:
  type: sqlite

redis:

mail:
  host: smtp.gmail.com
  user: SMTP_USER
  password: SMTP_PASSWORD
```

Upper-case values such as `DJANGO_SECRET_KEY` need to be specified as constants
in file `djevops/secrets.py`.

Most config values are optional. Fill in the ones you want and run
`djevops deploy`. djevops then clones your Git repo on the `server` and starts
(and monitors) all services.

## Features

<details>
<summary>SSL certificates</summary>

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
<summary>Database backups</summary>

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

## Development

Install the `test` dependencies from [`pyproject.toml`](pyproject.toml). The
easiest way I know for doing this is with [`uv`](https://docs.astral.sh/uv/):

```
uv venv
source .venv/bin/activate
uv sync --no-install-project --extra test
```

Then, you can do `python -m unittest` to run tests. This requires some API keys
and environment variables.
