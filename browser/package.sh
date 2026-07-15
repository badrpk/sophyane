#!/usr/bin/env bash
# Build Sophyane Browser release artifact for GitHub Releases
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER=$(python3 -c "import pathlib; t=pathlib.Path('$ROOT/src/sophyane/version.py').read_text(); import re; print(re.search(r'\"([0-9.]+)\"', t).group(1))")
OUTDIR="$ROOT/dist"
NAME="sophyane-browser-${VER}"
STAGE=$(mktemp -d)
mkdir -p "$STAGE/$NAME/home" "$OUTDIR"
# sync latest home from package
cp -a "$ROOT/src/sophyane/browser/home/." "$STAGE/$NAME/home/"
cp "$ROOT/browser/install.sh" "$STAGE/$NAME/"
cp "$ROOT/browser/install.ps1" "$STAGE/$NAME/"
cp "$ROOT/browser/README.md" "$STAGE/$NAME/"
# wrapper
cat > "$STAGE/$NAME/sophyane-browser" <<'WRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
if command -v sophyane >/dev/null; then
  exec sophyane --browser "$@"
fi
echo "Install Sophyane first: curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh" >&2
exit 1
WRAP
chmod 755 "$STAGE/$NAME/sophyane-browser" "$STAGE/$NAME/install.sh"
tar -C "$STAGE" -czf "$OUTDIR/${NAME}.tar.gz" "$NAME"
# also copy to website/download for portal
mkdir -p "$ROOT/website/download"
cp "$OUTDIR/${NAME}.tar.gz" "$ROOT/website/download/sophyane-browser.tar.gz"
cp "$ROOT/browser/install.sh" "$ROOT/website/download/install-sophyane-browser.sh"
cp "$ROOT/browser/install.ps1" "$ROOT/website/download/install-sophyane-browser.ps1"
echo "Built $OUTDIR/${NAME}.tar.gz"
ls -la "$OUTDIR/${NAME}.tar.gz"
rm -rf "$STAGE"
