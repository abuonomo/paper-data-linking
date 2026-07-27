#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Wait for PostgreSQL to become available.
echo "Waiting for PostgreSQL to become available..."
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 1
done
echo "PostgreSQL is available"

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start the application
echo "Initialization Complete"
exec "$@"
