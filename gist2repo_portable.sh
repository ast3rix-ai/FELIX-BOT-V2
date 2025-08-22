#!/usr/bin/env bash
set -euo pipefail

GIST_URL="${GIST_URL:-}"
REPO_NAME="${REPO_NAME:-felix-bot-repro}"

if [[ -z "${GIST_URL}" ]]; then
  echo "ERROR: GIST_URL not set" >&2
  exit 1
fi

# deps
for cmd in curl jq unzip git rsync; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing dependency '$cmd'" >&2; exit 1; }
done

WORKDIR="$(pwd)/_gist_work"
EXPORT_DIR="$(pwd)/export"
rm -rf "$WORKDIR" "$EXPORT_DIR" && mkdir -p "$WORKDIR" "$EXPORT_DIR"

b64_decode() {
  # $1 in, $2 out; portable macOS/Linux
  python3 - "$1" "$2" <<'PY'
import sys, base64
inp, out = sys.argv[1], sys.argv[2]
with open(inp, 'rb') as f: data = f.read()
with open(out, 'wb') as g: g.write(base64.b64decode(data))
PY
}

GIST_ID="$(basename "$GIST_URL")"
GIST_JSON="$WORKDIR/gist.json"

echo "→ Fetching gist metadata for $GIST_ID"
curl -fsSL "https://api.github.com/gists/$GIST_ID" -o "$GIST_JSON"

FILES_COUNT="$(jq '.files | length' "$GIST_JSON")"
[[ "$FILES_COUNT" -gt 0 ]] || { echo "ERROR: Gist has no files" >&2; exit 1; }

echo "→ Found $FILES_COUNT file(s):"
jq -r '.files[] | .filename' "$GIST_JSON"

ZIP_PATH="$WORKDIR/archive.zip"
FOUND_ARCHIVE=0
PLAIN_FILES_DIR="$WORKDIR/plain"
mkdir -p "$PLAIN_FILES_DIR"

# Iterate without mapfile (bash3-friendly)
jq -r '.files | to_entries[] | "\(.value.filename)\t\(.value.raw_url)"' "$GIST_JSON" |
while IFS=$'\t' read -r name url; do
  path="$WORKDIR/$name"
  echo "→ Downloading $name"
  curl -fsSL "$url" -o "$path"
  if [[ "$name" == *.zip ]]; then
    echo "→ Detected raw ZIP: $name"
    cp "$path" "$ZIP_PATH"
    FOUND_ARCHIVE=1
  elif [[ "$name" == *.b64 ]]; then
    echo "→ Detected Base64 file: $name (decoding to ZIP)"
    b64_decode "$path" "$ZIP_PATH" || { echo "ERROR: base64 decode failed for $name" >&2; exit 1; }
    FOUND_ARCHIVE=1
  else
    head4="$(LC_ALL=C head -c 4 "$path" | tr -d '\n' || true)"
    if [[ "$head4" == "UEsD" ]]; then
      echo "→ Heuristic: looks like Base64 ZIP, decoding $name"
      b64_decode "$path" "$ZIP_PATH" || { echo "ERROR: base64 decode failed for $name" >&2; exit 1; }
      FOUND_ARCHIVE=1
    else
      echo "→ Treating $name as plain source file"
      mkdir -p "$(dirname "$PLAIN_FILES_DIR/$name")"
      cp "$path" "$PLAIN_FILES_DIR/$name"
    fi
  fi
  if [[ "$FOUND_ARCHIVE" -eq 1 ]]; then echo 1 > "$WORKDIR/.flag_zip"; fi
done

if [[ -f "$WORKDIR/.flag_zip" ]]; then FOUND_ARCHIVE=1; else FOUND_ARCHIVE=0; fi

if [[ "$FOUND_ARCHIVE" -eq 1 ]]; then
  echo "→ Unzipping archive to $EXPORT_DIR"
  unzip -q "$ZIP_PATH" -d "$EXPORT_DIR"
  set +e; entries=("$EXPORT_DIR"/*); set -e
  if [[ ${#entries[@]} -eq 1 && -d "${entries[0]}" ]]; then
    echo "→ Flattening top-level dir"
    rsync -a "${entries[0]}/" "$EXPORT_DIR/"
    rm -rf "${entries[0]}"
  fi
else
  echo "→ No archive found; copying plain files to $EXPORT_DIR"
  rsync -a "$PLAIN_FILES_DIR/" "$EXPORT_DIR/"
fi

# Scrub
cd "$EXPORT_DIR"
rm -f .env || true
find . -name "*.session" -delete || true
rm -rf .venv node_modules || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf .pytest_cache .mypy_cache .ruff_cache || true
find . -name "*.pyc" -delete || true

if [[ ! -f .env.example ]]; then
  cat > .env.example <<'EOT'
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=changeme
ACCOUNT=acc1
PAYLINK=https://example.com/pay
EOT
fi

if [[ ! -f .gitignore ]]; then
  cat > .gitignore <<'EOT'
.env
.venv/
*.session
__pycache__/
.DS_Store
node_modules/
*.pyc
pytest_cache/
EOT
fi

if command -v gh >/dev/null 2>&1; then
  echo "→ Checking gh auth"
  if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
    exit 1
  fi
  base="$REPO_NAME"; n=0
  while gh repo view "${GITHUB_USER:-$(gh api user --jq .login)}/${REPO_NAME}" >/dev/null 2>&1; do
    n=$((n+1)); REPO_NAME="${base}-${n}"
  done
  echo "→ Creating public repo: ${REPO_NAME}"
  gh repo create "${REPO_NAME}" --public --source=. --remote=origin --push
  REPO_URL="https://github.com/$(gh api user --jq .login)/${REPO_NAME}"
  echo "✅ DONE. Repo URL: $REPO_URL"
else
  echo "ERROR: gh not installed. Install gh and re-run." >&2
  exit 1
fi
