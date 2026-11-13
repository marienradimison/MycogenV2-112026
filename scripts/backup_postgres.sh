#!/usr/bin/env bash
# Sauvegarde quotidienne de la base PostgreSQL (format compressé, restauration avec pg_restore).
# Le mot de passe est lu dans ~/.pgpass (droits 600). Les sauvegardes vont par défaut sur le disque Windows D:
# (visible depuis Windows, donc facile à copier hors du serveur). Conservation : 30 jours.
set -euo pipefail
DEST="${BACKUP_DIR:-/mnt/d/Sauvegardes/Mycogen}"
mkdir -p "$DEST"
STAMP="$(date +%Y-%m-%d_%H%M)"
pg_dump -h "${DB_HOST:-localhost}" -U "${DB_USER:-mycogen}" -w -F c -f "$DEST/mycogen_$STAMP.dump" "${DB_NAME:-mycogen}"
find "$DEST" -name 'mycogen_*.dump' -mtime +30 -delete
echo "Sauvegarde : $DEST/mycogen_$STAMP.dump"
