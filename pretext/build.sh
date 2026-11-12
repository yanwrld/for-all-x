#!/usr/bin/env bash
# Rebuild the PreTeXt edition of forall x: UBC edition from the LaTeX sources.
#
#   ./build.sh            convert LaTeX -> PreTeXt, then build the web version
#                         using the SVGs already in generated-assets/
#   ./build.sh images     also regenerate the tree/proof SVGs (needs pdflatex);
#                         do this whenever a tree or proof in the LaTeX changes
#
# Requires: python3 with lxml, the PreTeXt CLI (pip install -r requirements.txt),
# and, for images, a LaTeX installation with the forest package (texlive-pictures).
set -euo pipefail
cd "$(dirname "$0")"
PRETEXT=${PRETEXT:-pretext}
# the tree/proof images need prooftrees.sty and forallx-images.sty from latex/
export TEXINPUTS="$(pwd)/latex//:${TEXINPUTS:-}"

python3 scripts/latex2ptx.py
if [[ "${1:-}" == "images" ]]; then
  "$PRETEXT" generate latex-image -t web
  python3 scripts/measure_images.py
  python3 scripts/latex2ptx.py   # pick up the measured image widths
fi
"$PRETEXT" build web --no-generate
echo "Built: $(pwd)/output/web/index.html"
