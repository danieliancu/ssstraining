# Forge deploy script
cd /home/forge/sstcourses.co.uk
git pull origin $FORGE_SITE_BRANCH
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
sudo systemctl restart sst
