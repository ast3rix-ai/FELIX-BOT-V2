#!/usr/bin/env bash
set -euo pipefail

############################
# CONFIG (edit as needed)
############################
GIST_URL="${GIST_URL:-}"      # <-- Cursor will set this; or set manually before running
REPO_NAME="${REPO_NAME:-felix-bot-repro}"  # fallback repo name if none is inferred

############################
# Preflight
############################
if [[ -z "${GIST_URL}" ]]; then
  echo "ERROR: GIST_URL not set. Example:"
  echo "GIST_URL='https://gist.github.com/ast3rix-ai/6d465986d9611e3e78e09750f1afbc44' bash ./this_script.sh"
  exit 1
fi

# Dependencies
for cmd in curl jq unzip git; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: missing dependency '$cmd'"; exit 1; }
endonecho

# Optional: gh (GitHub CLI)
if ! command -v gh >/dev/null 2>&1; then
  echo "WARNING: 'gh' (GitHub CLI) not found. Install via:"
  echo "  macOS: brew install gh"
  echo "  Linux: sudo apt-get install gh    (or see https://cli.github.com/)"
fi

WORKDIR="$(pwd)/_gist_work"
EXPORT_DIR="$(pwd)/export"
rm -rf "$WORKDIR" "$EXPORT_DIR"
mkdir -p "$WORKDIR" "$EXPORT_DIR"

############################
# Fetch gist JSON and files
############################
# Extract gist ID from URL
GIST_ID="$(basename "$GIST_URL")"
if [[ "$GIST_ID" == "" || "$GIST_ID" == " " ]]; then
  echo "ERROR: Could not parse gist id from URL: $GIST_URL"
  exit 1
fi

echo "→ Fetching gist metadata for $GIST_ID"
GIST_JSON="$WORKDIR/gist.json"
curl -fsSL "https://api.github.com/gists/$GIST_ID" -o "$GIST_JSON"

FILES_COUNT="$(jq '.files | length' "$GIST_JSON")"
if [[ "$FILES_COUNT" -eq 0 ]]; then
  echo "ERROR: Gist has no files."
  exit 1
fi

RAW_URLS=($(jq -r '.files[] | .raw_url' "$GIST_JSON"))
FILENAMES=($(jq -r '.files[] | .filename' "$GIST_JSON"))

echo "→ Found $FILES_COUNT file(s):"
jq -r '.files[] | .filename' "$GIST_JSON"

############################
# Download & detect type
############################
ZIP_PATH="$WORKDIR/archive.zip"
FOUND_ARCHIVE=0
PLAIN_FILES_DIR="$WORKDIR/plain"

mkdir -p "$PLAIN_FILES_DIR"

for i in "${!RAW_URLS[@]}"; do
  name="${FILENAMES[$i]}"
  url="${RAW_URLS[$i]}"
  path="$WORKDIR/$name"
  echo "→ Downloading $name"
  curl -fsSL "$url" -o "$path"

  # Decide how to handle each file
  if [[ "$name" =~ \.zip$ ]]; then
    echo "→ Detected raw ZIP: $name"
    cp "$path" "$ZIP_PATH"
    FOUND_ARCHIVE=1
  elif [[ "$name" =~ \.b64$ ]]; then
    echo "→ Detected Base64 file: $name (attempting to decode to ZIP)"
    base64 -d "$path" > "$ZIP_PATH" || { echo "ERROR: base64 decode failed for $name"; exit 1; }
    FOUND_ARCHIVE=1
  else
    # Heuristic: if file *content* looks like base64 zip (starts with UEsDB), try decode
    head4="$(head -c 4 "$path" | tr -d '\n' || true)"
    if [[ "$head4" == "UEsD" ]]; then
      echo "→ Heuristic: looks like Base64 ZIP, decoding $name"
      base64 -d "$path" > "$ZIP_PATH" || { echo "ERROR: base64 decode failed for $name"; exit 1; }
      FOUND_ARCHIVE=1
    else
      echo "→ Treating $name as plain source file"
      cp "$path" "$PLAIN_FILES_DIR/$name"
    fi
  fi
done

############################
# Unpack
############################
if [[ "$FOUND_ARCHIVE" -eq 1 ]]; then
  echo "→ Unzipping archive to $EXPORT_DIR"
  unzip -q "$ZIP_PATH" -d "$EXPORT_DIR"
  # Some zips contain a top-level folder; flatten if there's only one
  shopt -s nullglob
  top=("$EXPORT_DIR"/*)
  if [[ ${#top[@]} -eq 1 && -d "${top[0]}" ]]; then
    echo "→ Flattening top-level dir"
    rsync -a "${top[0]}/" "$EXPORT_DIR/"
    rm -rf "${top[0]}"
  fi
else
  echo "→ No archive found; copying plain files to $EXPORT_DIR"
  rsync -a "$PLAIN_FILES_DIR/" "$EXPORT_DIR/"
fi

############################
# Scrub secrets & junk
############################
echo "→ Scrubbing sensitive files and caches"
cd "$EXPORT_DIR"
# Remove obvious secrets and noise
rm -f .env || true
rm -f **/*.session 2>/dev/null || true
rm -rf .venv node_modules **/__pycache__ .pytest_cache .mypy_cache .ruff_cache || true
find . -name "*.pyc" -delete || true
# Ensure example env (optional) so reviewers can run
if [[ ! -f ".env.example" ]]; then
  cat > .env.example <<'EOF'
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=changeme
ACCOUNT=acc1
PAYLINK=https://example.com/pay
EOF
fi
# Ensure a sensible .gitignore
if [[ ! -f ".gitignore" ]]; then
  cat > .gitignore <<'EOF'
.env
.venv/
*.session
__pycache__/
.DS_Store
node_modules/
*.pyc
pytest_cache/
EOF
fi

############################
# Create public repo with gh
############################
if command -v gh >/dev/null 2>&1; then
  echo "→ Checking gh auth"
  if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh is not authenticated."
    echo "Run: gh auth login   (then re-run this script)"
    exit 1
  fi

  # If repo exists, use a unique suffix
  base="${REPO_NAME}"
  n=0
  while gh repo view "${GITHUB_USER:-$(gh api user --jq .login)}/${REPO_NAME}" >/dev/null 2>&1; do
    n=$((n+1))
    REPO_NAME="${base}-${n}"
  done

  echo "→ Creating public repo: ${REPO_NAME}"
  gh repo create "${REPO_NAME}" --public --source=. --remote=origin --push
  REPO_URL="https://github.com/$(
    gh api user --jq .login
  )/${REPO_NAME}"
  echo "✅ DONE. Repo URL:"
  echo "$REPO_URL"
else
  echo "##############################################"
  echo "ERROR: gh (GitHub CLI) not installed or not found."
  echo "Install gh, run 'gh auth login', then from $EXPORT_DIR do:"
  echo "  git init"
  echo "  git add ."
  echo "  git commit -m 'repro'"
  echo "  gh repo create ${REPO_NAME} --public --source=. --remote=origin --push"
  echo "##############################################"
  exit 1
fi
