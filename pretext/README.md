# forall x: UBC edition — interactive PreTeXt edition

This directory holds a [PreTeXt](https://pretextbook.org) version of the book,
which builds an interactive web textbook:

- 86 exercises check the reader's answer (multiple choice built from the answer key);
- solutions from the answer key appear under each exercise, behind a **Solution** toggle,
  and are also collected in the Solutions appendix;
- cross-references open in place, the whole book is searchable, and pages work on phones;
- proof trees and Fitch-style natural deduction proofs are typeset by LaTeX, exactly as
  in the PDF, and shown as SVG images.

The LaTeX in `../Latex-Files` remains the single source of truth. The chapter
files in `source/` are **generated** from it, so edit the LaTeX and rebuild,
not the generated `.ptx` files.

## Building

```bash
pip install -r requirements.txt   # the PreTeXt CLI
./build.sh                        # convert LaTeX -> PreTeXt, build output/web/
./build.sh images                 # same, but also re-typeset the trees and proofs
```

`./build.sh` reuses the SVGs committed in `generated-assets/`. Run `./build.sh images`
(requires `pdflatex` with the `forest` package, e.g. Debian/Ubuntu
`texlive-latex-extra texlive-pictures texlive-fonts-recommended`) whenever a tree
or proof in the LaTeX changes, and commit the updated `generated-assets/` and
`scripts/image-sizes.json`.

Open `output/web/index.html` through a local web server (for example
`pretext view web`, or `python3 -m http.server -d output/web`).

## Hosting

The site is served at <https://fax.minegahara.net> as a static-assets
Cloudflare Worker (`wrangler.jsonc`). To deploy by hand after `./build.sh`:

```bash
npx wrangler deploy        # run in this directory; logs in with `npx wrangler login`
```

The GitHub Actions workflow `.github/workflows/pretext.yml` rebuilds everything
(including the images) on each push to `master` and deploys it. It needs two
repository secrets: `CLOUDFLARE_API_TOKEN` (made from the "Edit Cloudflare
Workers" token template) and `CLOUDFLARE_ACCOUNT_ID`.

## Layout

| Path | What it is |
| --- | --- |
| `scripts/latex2ptx.py` | Converter from this book's LaTeX to PreTeXt |
| `scripts/measure_images.py` | Records each tree/proof image's natural width, so it is shown at text size |
| `source/main.ptx`, `docinfo.ptx`, `frontmatter.ptx`, `backmatter.ptx` | Hand-written book structure, notation macros, title and back matter |
| `source/ch-*.ptx`, `app-*.ptx`, `preface.ptx`, `solutions-intro.ptx` | Generated from `Latex-Files/` |
| `wrangler.jsonc` | Cloudflare Worker that serves `output/web` at fax.minegahara.net |
| `latex/forallx-images.sty`, `latex/prooftrees.sty` | LaTeX support for the tree and proof images (from `forallx-ubc.sty`) |
| `generated-assets/latex-image/` | The typeset trees and proofs (SVG) |
| `assets/` | Cover and photo |

## How the conversion maps the LaTeX

| LaTeX | PreTeXt |
| --- | --- |
| `\chapter`, `\section`, `\subsection`, `\paragraph` | `chapter`, `section`, `subsection`, `paragraphs` |
| `\practiceproblems`, `\problempart` | `exercises` with one `subexercises` per Part |
| `\solutionpart{…}{label}` in the answer key | `solution` on the matching exercise(s) |
| `\nextSeq…\lastSeq are valid.` keys, and one-word answers (tautology, consistent, …) | Multiple-choice exercises that check the answer |
| `earg` / `ekey` (arguments, symbolization keys) | Description lists, or compact two-column tables |
| `prooftree`, `ndproof` | `latex-image` (rendered to SVG) |
| truth tables, `partialmodel` | `tabular` |
| `\factoidbox` | `assemblage` |
| `genaipractice` | `note` |
| `\enot`, `\eand`, `\metaA`, `\script`, … | MathJax macros in `docinfo.ptx` |
