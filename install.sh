#!/bin/bash

# Installs a Django app and all dependencies on a fresh Debian 12. To use,
# upload this file and a suitable .bashrc to /root, then execute this script as
# root.

# Error handling:
set -e
trap 'echo "Error on line $LINENO"' ERR

log() {
    echo -e "\n\033[0;32m`date +%H:%M:%S`\033[0m \033[0;93m$1\033[0m"
}

error() {
    echo -e "\n\033[0;32m`date +%H:%M:%S`\033[0m \033[0;91m$1\033[0m"
    exit 1
}

################################################################################
#                                  Settings                                    #
################################################################################

chmod 600 .bashrc
source .bashrc

if [ -z "$HOST_NAME" ]; then
  error 'Please set HOST_NAME in your .bashrc. For example: export HOST_NAME=my.domain.com'
fi

if [ -z "$GIT_SERVER" ]; then
  GIT_SERVER=github.com
fi

if [ -z "$GIT_REPO_NAME" ]; then
  error 'Please set GIT_REPO_NAME in your .bashrc. For example: export GIT_REPO_NAME=mherrmann/djevops'
fi

if [ -z "$GIT_REPO_BRANCH" ]; then
  GIT_REPO_BRANCH=main
fi

if [ -n "$GIT_REPO_PUBKEY" ]; then
  if [ -z "$GIT_REPO_PRIVKEY" ]; then
    error 'You must set GIT_REPO_PRIVKEY when using GIT_REPO_PUBKEY.'
  fi
  GIT_REPO_URL="git@${GIT_SERVER}:${GIT_REPO_NAME}.git"
else
  GIT_REPO_URL="https://${GIT_SERVER}/${GIT_REPO_NAME}.git"
fi

################################################################################
#                                 Settings end                                 #
################################################################################


################################################################################
#                                 Script start                                 #
################################################################################

log 'Setting hostname...'
hostnamectl set-hostname "$HOST_NAME"

log 'Updating system...'
apt-get update > /dev/null
apt-get upgrade -y > /dev/null

log 'Installing git...'
apt-get install git-core -y > /dev/null

log 'Configuring git to avoid warnings when pulling...'
git config --global pull.rebase true

log 'Creating application users...'
groupadd --system django
useradd --system --gid django --shell /bin/bash django
mkdir -p /home/django
chown django /home/django
chmod 700 /home/django

if [ -n "$GIT_REPO_PUBKEY" ]; then
  log 'Setting up SSH keys for cloning the Git repository...'
  mkdir -p .ssh
  echo "$GIT_REPO_PUBKEY" > .ssh/id_rsa.pub
  chmod 644 .ssh/id_rsa.pub
  echo -e "$GIT_REPO_PRIVKEY" > .ssh/id_rsa
  chmod 600 .ssh/id_rsa
fi

log 'Adding git repository server to known hosts...'
ssh-keyscan -H ${GIT_SERVER} >> .ssh/known_hosts 2>/dev/null
chmod 600 .ssh/known_hosts

log 'Cloning the repository...'
git clone -q -b ${GIT_REPO_BRANCH} ${GIT_REPO_URL} /srv/app

if [ ! -f /srv/app/requirements.txt ]; then
  error 'Please create a requirements.txt file with your dependencies in your repository.'
fi

log 'Setting up bash profiles...'
ln -sf /opt/djevops/conf/.bash_profile .
ln -sf /opt/djevops/conf/.bash_profile /home/django

echo "export HOST_NAME=$HOST_NAME" > /home/django/.bashrc
echo 'export SQLITE_DB_FILE=/var/lib/django/db.sqlite3' >> /home/django/.bashrc
echo 'export STATIC_ROOT=/srv/static' >> /home/django/.bashrc
echo 'export PATH="/srv/venv/bin:$PATH"' >> /home/django/.bashrc
if [ -f /srv/app/conf/django.bashrc ]; then
  /usr/bin/envsubst < /srv/app/conf/django.bashrc >> /home/django/.bashrc
fi
chown django:django /home/django/.bashrc

log 'Creating data directory...'
mkdir -p /var/lib/django
chown django:django /var/lib/django

if [ -n "$SMTP_HOST" ]; then
  # Only allow local access to port 25:
  log 'Installing iptables-persistent...'
  echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
  echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
  apt-get -y install iptables-persistent -y > /dev/null

  log 'Configuring iptables...'
  iptables -A INPUT -i lo -p tcp --dport 25 -j ACCEPT
  iptables -A INPUT -p tcp --dport 25 -j REJECT

  # Save iptables rules so they persist across restarts. At the time of this
  # writing, there is no open IPv6 port, so enough to save rules.v*4*.
  iptables-save > /etc/iptables/rules.v4

  log 'Installing Postfix...'
  debconf-set-selections <<< "postfix postfix/mailname string $HOST_NAME"
  debconf-set-selections <<< "postfix postfix/main_mailer_type string 'Internet Site'"
  apt-get install postfix mailutils libsasl2-2 ca-certificates libsasl2-modules -y > /dev/null

  log 'Configuring Postfix...'
  # The SMTP_USER credentials can for example be created in the AWS SES console
  # under "SMTP settings" with button "Create SMTP credentials". (Be sure to do
  # this in the correct AWS region!)
  echo "$HOST_NAME" > /etc/mailname
  chown postfix /etc/mailname
  envsubst '$SMTP_HOST $HOST_NAME' < /opt/djevops/conf/postfix/main.cf > /etc/postfix/main.cf
  envsubst < /opt/djevops/conf/postfix/sasl_passwd > /etc/postfix/sasl_passwd
  chown postfix /etc/postfix
  postmap /etc/postfix/sasl_passwd
  chmod 400 /etc/postfix/sasl_passwd
  chown postfix /etc/postfix/sasl_passwd
  envsubst < /opt/djevops/conf/postfix/generic > /etc/postfix/generic
  rm -f /etc/postfix/generic.db
  postmap /etc/postfix/generic
  chown postfix /etc/postfix/generic
  /etc/init.d/postfix reload > /dev/null
fi

log 'Creating directories for static files...'
mkdir /srv/static

log 'Installing OS dependencies for our Python environment...'
apt-get install python3-venv -y > /dev/null

log 'Creating virtual environment...'
python3 -m venv /srv/venv > /dev/null

log 'Installing Python dependencies...'
/opt/djevops/bin/install-python-deps.sh

if /srv/venv/bin/python -c "import celery" &>/dev/null; then
  USES_CELERY=true
else
  USES_CELERY=false
fi

log 'Checking Django settings...'
su -c "/opt/djevops/bin/manage.sh shell --pythonpath /opt/djevops/bin -c 'from check_django_settings import main; main()' -v 0" - django

if $USES_CELERY; then
  log 'Celery detected. Installing Redis...'
  apt-get install redis-server -y > /dev/null
fi

log 'Migrating database...'
/opt/djevops/bin/migrate-db.sh

log 'Collecting static files...'
/opt/djevops/bin/collect-static-files.sh

log 'Initializing run/ directory...'
/opt/djevops/bin/init-run-dir.sh

log 'Installing Supervisor...'
apt-get install supervisor -y > /dev/null

log 'Configuring Supervisor...'
ln -s /opt/djevops/conf/supervisor/gunicorn.conf /etc/supervisor/conf.d

if $USES_CELERY; then
  ln -s /opt/djevops/conf/supervisor/beat.conf /etc/supervisor/conf.d
  ln -s /opt/djevops/conf/supervisor/worker.conf /etc/supervisor/conf.d
fi

log 'Starting services...'
supervisorctl reread > /dev/null
supervisorctl update > /dev/null

log 'Installing Nginx...'
apt-get install nginx -y > /dev/null

log 'Creating Nginx includes directory...'
mkdir /etc/nginx/includes

log 'Creating Nginx config...'
envsubst < /opt/djevops/conf/nginx/server-name > /etc/nginx/includes/server-name
ln -s /opt/djevops/conf/nginx/django /etc/nginx/includes/django
touch /etc/nginx/includes/ssl

log 'Applying Nginx config...'
ln -s /opt/djevops/conf/nginx/nginx /etc/nginx/sites-available/django
ln -s /etc/nginx/sites-available/django /etc/nginx/sites-enabled/django
rm /etc/nginx/sites-enabled/default

log 'Starting Nginx...'
service nginx restart

log 'Generating SSL certificates...'
apt-get install certbot python3-certbot-nginx -y > /dev/null
certbot register --quiet --email $ADMIN_EMAIL --agree-tos
certbot certonly --nginx --quiet --cert-name main -d $HOST_NAME
ln -sf /opt/djevops/conf/nginx/ssl /etc/nginx/includes/ssl
service nginx restart

log "The server is now serving requests at $HOST_NAME!"

# Now do less important things that are not required for serving requests:

log 'Setting up logrotate...'
ln -s /opt/djevops/conf/logrotate /etc/logrotate.d/django

if [ -f /opt/djevops/conf/crontab ]; then
  log 'Setting up crontab...'
  ln -s /opt/djevops/bin/cronic /usr/bin/cronic
  sed "s/\$ADMIN_EMAIL/$ADMIN_EMAIL/g" /opt/djevops/conf/crontab > crontab
  crontab crontab
  rm crontab
fi

log 'Setting up automatic updates...'
apt-get install unattended-upgrades -y > /dev/null
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades

log 'Done.'
