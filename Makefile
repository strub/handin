# -*- Makefile -*-

# --------------------------------------------------------------------
.PHONY: default serve release cleardb migrations backup __force__

HOST = vps.strub.nu

# --------------------------------------------------------------------
default: serve
	@true

# --------------------------------------------------------------------
serve: __force__
	python3 manage.py runserver

# --------------------------------------------------------------------
cleardb: __force__
	find . -path '*/migrations/*.py' -not -name '__init__.py' -delete
	find . -path '*/migrations/__pycache__/*.pyc'  -delete
	rm -rf db.sqlite3 media

# --------------------------------------------------------------------
migrations:
	python manage.py makemigrations
	python manage.py migrate

# --------------------------------------------------------------------
release: __force__
	rsync -Ravt --delete \
	  --perms --no-group --chmod=ug=rwX,o=rX \
	  --exclude='*.pyc' --exclude='__pycache__' \
	  --exclude='migrations/*.py' --exclude='media/' \
	  --exclude='*.sqlite3' --exclude='.git*' \
	  . $(HOST):/opt/handin/handin
	ssh vps.strub.nu 'sudo -i systemctl stop gunicorn'

# --------------------------------------------------------------------
backup: __force__
	./manage.py dbbackup    --settings=handin.settings.deploy
	./manage.py mediabackup --settings=handin.settings.deploy

# --------------------------------------------------------------------
release-restart: release
	ssh $(HOST) 'sudo /etc/init.d/apache2 restart'
