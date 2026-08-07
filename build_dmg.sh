#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="InvoiceApp"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
BUILD_DIR="$ROOT_DIR/build/dmg"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
STAGE_DIR="$BUILD_DIR/stage"
DMG_PATH="$ROOT_DIR/$APP_NAME.dmg"
DMG_README="$ROOT_DIR/packaging/README_DMG.md"
PYINSTALLER_TARGET_ARCH="${PYINSTALLER_TARGET_ARCH:-$(uname -m)}"


validate_clean_bundle() {
    local target="$1"
    local failed=0
    local matches
    matches="$(mktemp)"

    find "$target" -type f \( \
        -name "db.sqlite3" -o \
        -name "*.sqlite3" -o \
        -name "*.db" -o \
        -name "test_*.sqlite3" -o \
        -name "*test*.sqlite3" -o \
        -name "invoice_backup_*.zip" -o \
        -name "*.bak" -o \
        -name "*.backup" -o \
        -name "*.log" -o \
        -name "*.pdf" -o \
        -name "*.xlsx" -o \
        -name "*.csv" \
    \) -print > "$matches"

    find "$target" -type f \( \
        -path "*/media/*" -o \
        -path "*/backups/*" -o \
        -path "*/logs/*" \
    \) ! -name ".gitkeep" -print >> "$matches"

    if [ -s "$matches" ]; then
        echo "ERROR: Sensitive or generated data files were found in $target:"
        cat "$matches"
        failed=1
    fi
    rm -f "$matches"

    if grep -R -a -l "Admin@12345" "$target" >/dev/null 2>&1; then
        echo "ERROR: Default development password string found in $target."
        grep -R -a -l "Admin@12345" "$target" || true
        failed=1
    fi

    if grep -R -a -l "create_default_admin" "$target" >/dev/null 2>&1; then
        echo "ERROR: Developer-only default admin command found in $target."
        grep -R -a -l "create_default_admin" "$target" || true
        failed=1
    fi

    if [ "$failed" -ne 0 ]; then
        exit 1
    fi
}


if [ "${1:-}" = "--validate-only" ]; then
    if [ -z "${2:-}" ]; then
        echo "Usage: ./build_dmg.sh --validate-only /path/to/app-or-stage"
        exit 2
    fi
    validate_clean_bundle "$2"
    echo "Validation passed: $2 contains no forbidden bundled data."
    exit 0
fi


if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ ! -f "$DMG_README" ]; then
    echo "ERROR: Missing DMG README at $DMG_README"
    exit 1
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
    echo "ERROR: PyInstaller is required for DMG packaging."
    echo "Install packaging dependencies with:"
    echo "  $PYTHON_BIN -m pip install -r requirements-packaging.txt"
    exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
    echo "ERROR: hdiutil is required to create a macOS DMG."
    exit 1
fi

if [ "$PYINSTALLER_TARGET_ARCH" != "universal2" ] && ! xcrun --find lipo >/dev/null 2>&1; then
    echo "ERROR: Apple Command Line Tools are required for a $PYINSTALLER_TARGET_ARCH macOS bundle."
    echo "Install or repair them, then rerun ./build_dmg.sh:"
    echo "  xcode-select --install"
    exit 1
fi

echo "Cleaning previous package build output..."
rm -rf "$BUILD_DIR" "$APP_BUNDLE" "$DMG_PATH"
mkdir -p "$BUILD_DIR"
export PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller_config"

migration_args=()
for migration in "$ROOT_DIR"/billing/migrations/[0-9]*.py; do
    [ -e "$migration" ] || continue
    migration_name="$(basename "$migration" .py)"
    migration_args+=(--hidden-import "billing.migrations.$migration_name")
done

echo "Building clean macOS app bundle..."
"$PYTHON_BIN" -m PyInstaller \
    --name "$APP_NAME" \
    --windowed \
    --clean \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR/pyinstaller" \
    --specpath "$BUILD_DIR" \
    --target-arch "$PYINSTALLER_TARGET_ARCH" \
    --exclude-module "billing.management.commands.create_default_admin" \
    --hidden-import "django.core.management.commands.migrate" \
    "${migration_args[@]}" \
    --add-data "$ROOT_DIR/templates:templates" \
    --add-data "$ROOT_DIR/static:static" \
    "$ROOT_DIR/start_app.py"

echo "Validating app bundle for forbidden data..."
validate_clean_bundle "$APP_BUNDLE"

echo "Preparing DMG staging folder..."
mkdir -p "$STAGE_DIR"
cp -R "$APP_BUNDLE" "$STAGE_DIR/"
cp "$DMG_README" "$STAGE_DIR/README.md"
ln -s /Applications "$STAGE_DIR/Applications"

echo "Validating DMG staging folder..."
validate_clean_bundle "$STAGE_DIR"

echo "Creating $DMG_PATH..."
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"

echo "DMG created successfully: $DMG_PATH"
echo "Runtime data is created outside the app at ~/Documents/InvoiceApp/ on first launch."
