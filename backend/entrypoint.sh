#!/usr/bin/env bash
set -e

echo "Postgres kutilmoqda..."
until python -c "
import os, sys, psycopg
try:
    psycopg.connect(
        host=os.getenv('POSTGRES_HOST', 'postgres'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        dbname=os.getenv('POSTGRES_DB', 'speaking'),
        user=os.getenv('POSTGRES_USER', 'speaking'),
        password=os.getenv('POSTGRES_PASSWORD', 'speaking'),
        connect_timeout=3,
    ).close()
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
"; do
  sleep 2
done

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "${SEED_CONTENT:-0}" = "1" ]; then
  # Har yo'nalish — o'z fayli, o'z tartibi. Grammatika birinchi: iboralar,
  # shadowing va rol suhbat unga bog'lanadi (§related_topics).
  python manage.py seed_content
  python manage.py seed_content --file fixtures/seed_phrases.json
  python manage.py seed_content --file fixtures/seed_shadowing.json
  python manage.py seed_content --file fixtures/seed_roleplay.json
fi

exec "$@"
