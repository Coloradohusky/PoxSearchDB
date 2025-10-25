#!/usr/bin/env bash

# Exit on error
set -o errexit

# Collect static files, run migrations, and start server
echo "Running migrations..."
python manage.py makemigrations extracteddata --noinput || true
python manage.py migrate --noinput
python manage.py migrate extracteddata --noinput

# Optionally create a superuser automatically (if env vars set)
if [ "$DJANGO_SUPERUSER_USERNAME" ] && [ "$DJANGO_SUPERUSER_EMAIL" ] && [ "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "Creating superuser..."
  python manage.py createsuperuser \
    --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    --email "$DJANGO_SUPERUSER_EMAIL" || true
else
  echo "Skipping superuser creation (env vars not set)"
fi

python manage.py collectstatic --noinput

if [ "${DELETE_DATA,,}" = "true" ]; then
  echo "Removing data"
  python manage.py shell -c "
from django.apps import apps

for model in apps.get_app_config('extracteddata').get_models():
    model.objects.all().delete()
"
fi

echo "Starting Gunicorn..."
exec gunicorn PoxSearchDB.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 2 --access-logfile - --error-logfile - --log-level debug --timeout 300
