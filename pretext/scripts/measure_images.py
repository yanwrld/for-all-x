#!/usr/bin/env python3
"""Record the natural width (in pt) of each generated latex-image SVG.

latex2ptx.py reads scripts/image-sizes.json to give every tree and proof an
<image width="..."> that keeps its text at roughly the size of the body text.
Run this after `pretext generate latex-image`, then rerun latex2ptx.py.
Generated files no longer referenced from the source are deleted.
"""
import glob, json, os, re
here = os.path.dirname(os.path.abspath(__file__))
labels = set()
for f in glob.glob(os.path.join(here, "..", "source", "*.ptx")):
    with open(f) as fh:
        labels.update(re.findall(r'<latex-image label="([^"]+)"', fh.read()))
sizes = {}
for f in sorted(glob.glob(os.path.join(here, "..", "generated-assets", "latex-image", "*"))):
    name = os.path.splitext(os.path.basename(f))[0]
    if name not in labels:
        os.remove(f)
        continue
    if not f.endswith(".svg"):
        continue
    base = re.sub(r"^(\w+-[0-9a-f]{10})-\d+$", r"\1", name)
    with open(f) as fh:
        head = fh.read(2000)
    m = re.search(r'<svg[^>]*\bwidth="([\d.]+)(pt|px)?"', head)
    if m:
        sizes[base] = round(float(m.group(1)), 1)
with open(os.path.join(here, "image-sizes.json"), "w") as fh:
    json.dump(sizes, fh, indent=0, sort_keys=True)
print("measured %d images" % len(sizes))
