import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from django.conf import settings
from django.db import connections
from django.utils import timezone

from .services import get_application_settings


BACKUP_NAME_PATTERN = re.compile(r"^invoice_backup_\d{8}_\d{6}(?:_\d+)?\.zip$")
RESTORE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
DATABASE_ARCNAME = "database/db.sqlite3"
MANIFEST_ARCNAME = "backup_manifest.json"
SETTINGS_ARCNAME = "settings/app_settings.json"
ALLOWED_MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".xlsx", ".xls", ".csv"}
EXECUTABLE_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".jar",
    ".js",
    ".msi",
    ".ps1",
    ".py",
    ".scr",
    ".sh",
    ".vbs",
}


class BackupError(Exception):
    pass


class RestoreValidationError(Exception):
    pass


class RestoreError(Exception):
    pass


@dataclass(frozen=True)
class BackupRecord:
    name: str
    size: int
    created_at: object


@dataclass(frozen=True)
class RestoreResult:
    safety_backup_name: str
    restored_media_files: int


def backup_root():
    root = Path(getattr(settings, "BACKUP_ROOT", settings.BASE_DIR / "backups")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def pending_restore_root():
    root = backup_root() / "_pending_restore"
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_local_backups():
    records = []
    for path in backup_root().glob("invoice_backup_*.zip"):
        if path.is_file() and BACKUP_NAME_PATTERN.match(path.name):
            stat = path.stat()
            records.append(
                BackupRecord(
                    name=path.name,
                    size=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
                )
            )
    return sorted(records, key=lambda record: record.created_at, reverse=True)


def backup_file_path(filename):
    if not BACKUP_NAME_PATTERN.match(filename or ""):
        raise BackupError("Invalid backup filename.")
    path = (backup_root() / filename).resolve()
    if backup_root() not in path.parents:
        raise BackupError("Unsafe backup path.")
    if not path.exists() or not path.is_file():
        raise BackupError("Backup file was not found.")
    return path


def create_local_backup(reason="manual"):
    root = backup_root()
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    backup_path = _unique_backup_path(root / f"invoice_backup_{timestamp}.zip")

    try:
        with tempfile.TemporaryDirectory(prefix="backup_", dir=str(root)) as temp_dir:
            settings_payload = _settings_payload()
            temp_db_path = Path(temp_dir) / "db.sqlite3"
            _write_sqlite_snapshot(temp_db_path)
            manifest = _backup_manifest(reason)

            with ZipFile(backup_path, "w", ZIP_DEFLATED) as archive:
                archive.write(temp_db_path, DATABASE_ARCNAME)
                archive.writestr(SETTINGS_ARCNAME, json.dumps(settings_payload, indent=2, sort_keys=True))
                media_files = _write_media_files(archive)
                manifest["media_file_count"] = media_files
                archive.writestr(MANIFEST_ARCNAME, json.dumps(manifest, indent=2, sort_keys=True))
    except Exception as exc:
        if backup_path.exists():
            backup_path.unlink()
        raise BackupError("Unable to create local backup.") from exc

    return backup_path


def save_pending_restore(uploaded_file):
    token = timezone.now().strftime("%Y%m%d%H%M%S%f")
    path = (pending_restore_root() / f"{token}.zip").resolve()
    if pending_restore_root() not in path.parents:
        raise RestoreValidationError("Unsafe restore upload path.")

    with open(path, "wb") as target:
        for chunk in uploaded_file.chunks():
            target.write(chunk)

    try:
        validation = validate_backup_zip(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return token, validation


def pending_restore_path(token):
    if not RESTORE_TOKEN_PATTERN.match(token or ""):
        raise RestoreValidationError("Invalid restore confirmation token.")
    path = (pending_restore_root() / f"{token}.zip").resolve()
    if pending_restore_root() not in path.parents:
        raise RestoreValidationError("Unsafe restore path.")
    if not path.exists() or not path.is_file():
        raise RestoreValidationError("Pending restore backup was not found.")
    return path


def cleanup_pending_restore(token):
    try:
        pending_restore_path(token).unlink(missing_ok=True)
    except RestoreValidationError:
        return


def validate_backup_zip(path):
    path = Path(path)
    if path.suffix.lower() != ".zip" or not is_zipfile(path):
        raise RestoreValidationError("Upload a valid backup ZIP file.")

    found_database = False
    found_manifest = False
    media_file_count = 0

    with ZipFile(path) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RestoreValidationError("Backup ZIP appears to be corrupt.")

        for info in archive.infolist():
            if not info.filename or info.filename.endswith("/"):
                continue
            safe_name = _validate_zip_member(info)
            if safe_name == DATABASE_ARCNAME:
                found_database = True
            elif safe_name == MANIFEST_ARCNAME:
                found_manifest = True
            elif safe_name.startswith("media/"):
                media_file_count += 1

        if found_database:
            with archive.open(DATABASE_ARCNAME) as database_file:
                if database_file.read(16) != b"SQLite format 3\x00":
                    raise RestoreValidationError("Backup ZIP does not contain a valid SQLite database.")

    if not found_database:
        raise RestoreValidationError("Backup ZIP does not contain the SQLite database.")
    if not found_manifest:
        raise RestoreValidationError("Backup ZIP does not contain the backup manifest.")

    return {
        "database": found_database,
        "manifest": found_manifest,
        "media_file_count": media_file_count,
    }


def restore_local_backup(path):
    validation = validate_backup_zip(path)
    extract_root = Path(tempfile.mkdtemp(prefix=".restore_extract_", dir=str(settings.BASE_DIR))).resolve()
    work_root = Path(tempfile.mkdtemp(prefix=".restore_apply_", dir=str(settings.BASE_DIR))).resolve()

    try:
        _safe_extract_backup(path, extract_root)
        source_db = extract_root / DATABASE_ARCNAME
        source_media = extract_root / "media"
        staged_db = work_root / "db.sqlite3"
        staged_media = work_root / "media"
        shutil.copy2(source_db, staged_db)
        if source_media.exists():
            shutil.copytree(source_media, staged_media)
        else:
            staged_media.mkdir()

        safety_backup = create_local_backup(reason="pre_restore")
        restored_media_files = validation["media_file_count"]
        _apply_restore(staged_db, staged_media, work_root)
    except RestoreValidationError:
        raise
    except Exception as exc:
        raise RestoreError("Restore failed. Existing data was left unchanged where possible.") from exc
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)
        shutil.rmtree(work_root, ignore_errors=True)

    return RestoreResult(safety_backup_name=safety_backup.name, restored_media_files=restored_media_files)


def _unique_backup_path(path):
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise BackupError("Could not allocate a backup filename.")


def _write_sqlite_snapshot(output_path):
    connection = connections["default"]
    if connection.vendor != "sqlite":
        raise BackupError("Only SQLite backup is supported for this local application.")
    database_name = str(connection.settings_dict["NAME"])
    if database_name.startswith("file:") or database_name == ":memory:":
        sqlite3.connect(output_path).close()
        return

    database_path = Path(database_name).resolve()
    if not database_path.exists():
        raise BackupError("SQLite database file was not found.")

    connection.close()
    shutil.copy2(database_path, output_path)


def _backup_manifest(reason):
    return {
        "application": "Local Invoice Generation System",
        "format_version": 1,
        "created_at": timezone.localtime().isoformat(),
        "reason": reason,
        "database": DATABASE_ARCNAME,
        "settings": SETTINGS_ARCNAME,
    }


def _settings_payload():
    app_settings = get_application_settings()
    if not app_settings:
        return {}
    return {
        "default_gst_percentage": str(app_settings.default_gst_percentage),
        "default_terms_and_conditions": app_settings.default_terms_and_conditions,
        "default_declaration": app_settings.default_declaration,
        "default_payment_terms": app_settings.default_payment_terms,
        "invoice_number_format": app_settings.invoice_number_format,
        "date_separator": app_settings.date_separator,
        "prefix_separator": app_settings.prefix_separator,
        "running_sequence_length": app_settings.running_sequence_length,
    }


def _write_media_files(archive):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not media_root.exists():
        return 0

    count = 0
    for path in media_root.rglob("*"):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(media_root).parts):
            continue
        extension = path.suffix.lower()
        if extension not in ALLOWED_MEDIA_EXTENSIONS:
            continue
        relative_path = path.relative_to(media_root).as_posix()
        archive.write(path, f"media/{relative_path}")
        count += 1
    return count


def _validate_zip_member(info):
    name = info.filename
    if "\\" in name:
        raise RestoreValidationError("Backup ZIP contains an unsafe file path.")
    if _is_zip_symlink(info):
        raise RestoreValidationError("Backup ZIP must not contain symbolic links.")

    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise RestoreValidationError("Backup ZIP contains an unsafe file path.")

    safe_name = path.as_posix()
    suffix = path.suffix.lower()
    if suffix in EXECUTABLE_EXTENSIONS:
        raise RestoreValidationError("Backup ZIP must not contain executable files.")

    if safe_name in {DATABASE_ARCNAME, MANIFEST_ARCNAME, SETTINGS_ARCNAME}:
        return safe_name
    if safe_name.startswith("media/"):
        if suffix not in ALLOWED_MEDIA_EXTENSIONS:
            raise RestoreValidationError("Backup ZIP contains an unsupported media file type.")
        return safe_name
    raise RestoreValidationError("Backup ZIP contains unexpected files.")


def _is_zip_symlink(info):
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type == 0o120000


def _safe_extract_backup(path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.filename or info.filename.endswith("/"):
                continue
            safe_name = _validate_zip_member(info)
            target = (destination / safe_name).resolve()
            if destination not in target.parents:
                raise RestoreValidationError("Backup ZIP contains an unsafe extraction path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)


def _apply_restore(staged_db, staged_media, work_root):
    db_path = _database_path()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_root.parent.mkdir(parents=True, exist_ok=True)
    previous_media = work_root / "previous_media"
    media_swapped = False

    connections.close_all()
    try:
        if media_root.exists():
            media_root.rename(previous_media)
        staged_media.rename(media_root)
        (media_root / ".gitkeep").touch(exist_ok=True)
        media_swapped = True
        os.replace(staged_db, db_path)
        if previous_media.exists():
            shutil.rmtree(previous_media)
    except Exception:
        if media_swapped:
            shutil.rmtree(media_root, ignore_errors=True)
            if previous_media.exists():
                previous_media.rename(media_root)
        raise


def _database_path():
    database_name = str(connections["default"].settings_dict["NAME"])
    if database_name.startswith("file:") or database_name == ":memory:":
        raise RestoreError("Restore requires a file-based SQLite database.")
    path = Path(database_name).resolve()
    if path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
        raise RestoreError("Restore requires a SQLite database file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
