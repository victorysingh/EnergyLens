"""Delete generated outputs so the pipeline can be re-run from clean.

    python src/00_reset.py          keep the downloaded raw files
    python src/00_reset.py --raw    also delete data/raw (forces a fresh download)
"""

import shutil
import sys

from common import FIGURES, INTERIM, PROCESSED, RAW, ROOT

targets = [INTERIM, PROCESSED, FIGURES]
files = [ROOT / "RESULTS.md", ROOT / "reports" / "preview_dashboard.html", ROOT / "reports" / "mad_sensitivity.csv"]
if "--raw" in sys.argv:
    targets.append(RAW)

for d in targets:
    for p in d.glob("*"):
        if p.name == ".gitkeep":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    print(f"emptied {d.relative_to(ROOT)}")
for f in files:
    if f.exists():
        f.unlink()
        print(f"deleted {f.relative_to(ROOT)}")
