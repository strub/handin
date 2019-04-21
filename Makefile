# -*- Makefile -*-

# --------------------------------------------------------------------
.PHONY: __force__ default serve release cleardb
.PHONY: migrations reset-migrations backup

HOST     := vps.strub.nu
SETTINGS ?= handin.settings.development
MANAGE   := DJANGO_SETTINGS_MODULE=$(SETTINGS) python manage.py
APPNAME  := upload

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
	$(MANAGE) makemigrations
	$(MANAGE) migrate

# --------------------------------------------------------------------
reset-migrations: migrations
	$(MANAGE) showmigrations $(APPNAME)
	$(MANAGE) migrate --fake $(APPNAME) zero
	rm -f $(APPNAME)/migrations/*.py
	rm -f $(APPNAME)/migrations/__pycache__/*.pyc
	$(MANAGE) makemigrations $(APPNAME)
	$(MANAGE) migrate --fake-initial $(APPNAME)
	$(MANAGE) showmigrations $(APPNAME)

# --------------------------------------------------------------------
release: __force__
	rsync -Ravt --delete \
	  --perms --no-group --chmod=ug=rwX,o=rX \
	  --exclude='*.pyc' --exclude='__pycache__' \
	  --exclude='migrations/*.py' \
	  --exclude='media/' --exclude='autocorrect/' \
	  --exclude='*.sqlite3' --exclude='.git*' \
	  . $(HOST):/opt/handin/handin
	ssh vps.strub.nu 'sudo -i systemctl stop gunicorn'

# --------------------------------------------------------------------
backup: __force__
	$(MANAGE) dbbackup
	$(MANAGE) mediabackup
