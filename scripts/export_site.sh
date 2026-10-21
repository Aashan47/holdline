#!/usr/bin/env bash
# Copy the product site into a folder served as a static site.
# The live copy is www.aashanjaved.com/holdline/ (repo Aashan47/Portfolio-aashan, folder holdline/).
#   scripts/export_site.sh ../Portfolio-aashan/holdline
set -euo pipefail
dest="${1:?usage: scripts/export_site.sh <destination folder>}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$dest"
rsync -a --delete --exclude '.DS_Store' "$here/site/" "$dest/"
cp "$here/docs/architecture.svg" "$dest/architecture.svg"
echo "exported to $dest"
