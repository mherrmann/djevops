# djevops: Host Django on bare metal

djevops is a command-line tool for deploying Django web apps on Linux VPSs.
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

To get started with djevops, all you need is a Linux VPS running Ubuntu or
Debian. Install djevops on your local machine with `pip install djevops`. Then,
execute `djevops init` in your Django app's Git repository. You get a config
file that looks similar to the following:

```
server: 1.2.3.4

git:
  repo: mherrmann/djangotutorial
  branch: main
  key: GIT_REPO_PRIVKEY

services:
  web:
    type: django
    domains: [djangotutorial.herrmann.io]
    env:
      clear:
        DEBUG: "False"
        ALLOWED_HOSTS: djangotutorial.herrmann.io
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

Upper-case values such as `GIT_REPO_PRIVKEY` need to be specified as constants
in file `djevops/secrets.py`.

Fill in your preferred values and run `djevops deploy`. djevops then clones your
Git repo on the server and starts (and monitors) all services. Any domains you
supply in `domains` must have DNS A records pointing at the same IP as `server`.

<details>
<summary>Error emails</summary>

To receive emails when errors occur on your server, supply Django's `ADMINS`
setting in addition to the `mail` config above. For example, in `settings.py`:

```
ADMINS = [('Your Name', 'your@email.com)]
```

This requires Django setting `DEBUG` to be `False`.

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
