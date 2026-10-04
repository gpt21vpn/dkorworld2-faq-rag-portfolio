"""Safe SQLite online backup using sqlite3 backup API."""
from pathlib import Path
from datetime import datetime, timedelta
import os
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
candidates = [
    ROOT / "instance" / "site.db",
    ROOT / "site.db",
]
source = next((p for p in candidates if p.exists()), None)
if source is None:
    raise SystemExit("site.db not found")

backup_dir = Path(os.environ.get("DKOR_BACKUP_DIR", str(ROOT / "backups")))
backup_dir.mkdir(parents=True, exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
dest = backup_dir / f"site_{stamp}.db"

with sqlite3.connect(source) as src, sqlite3.connect(dest) as dst:
    src.backup(dst)

retention_days = int(os.environ.get("DKOR_BACKUP_RETENTION_DAYS", "14"))
cutoff = datetime.now() - timedelta(days=retention_days)
for old in backup_dir.glob("site_*.db"):
    if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
        old.unlink(missing_ok=True)

print(f"Backup OK: {dest}")
