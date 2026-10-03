"""Step 1: download the BDG2 files we need and verify them.

The BDG2 repo stores its CSVs in Git LFS. For each file we:
  1. fetch the small LFS pointer (it states the expected SHA-256 and size),
  2. download the real file,
  3. check size and SHA-256 against the pointer,
  4. log URL, date, size and checksum to data/raw/SOURCES.md.

Files that already exist and pass the checksum are not downloaded again.
"""

import datetime as dt
import hashlib
import sys

import requests

from common import RAW, banner, load_config


def read_lfs_pointer(url):
    """Return (sha256, size) from a Git LFS pointer file."""
    text = requests.get(url, timeout=60).text
    fields = dict(line.split(" ", 1) for line in text.strip().splitlines())
    return fields["oid"].removeprefix("sha256:"), int(fields["size"])


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.replace(dest)


def main():
    cfg = load_config()["source"]
    banner("STEP 1: download BDG2 files")
    rows = []
    for rel in cfg["files"]:
        dest = RAW / rel.split("/")[-1]
        expected_sha, expected_size = read_lfs_pointer(cfg["pointer_base"] + rel)
        url = cfg["media_base"] + rel

        if dest.exists() and sha256_of(dest) == expected_sha:
            print(f"[skip] {dest.name} already present and checksum matches")
        else:
            print(f"[get ] {url}  ({expected_size / 1e6:.1f} MB)")
            download(url, dest)

        size, sha = dest.stat().st_size, sha256_of(dest)
        ok = size == expected_size and sha == expected_sha
        print(f"       size {size:,} bytes, sha256 {sha[:16]}...  verified={ok}")
        if not ok:
            sys.exit(f"Checksum/size mismatch for {dest.name}. Delete it and re-run.")
        rows.append((dest.name, url, size, sha))

    today = dt.date.today().isoformat()
    lines = [
        "# Raw data sources",
        "",
        f"Downloaded/verified on **{today}** by `src/01_download.py`.",
        "",
        "Source: Building Data Genome Project 2 (BDG2), public dataset,",
        f"<{cfg['repo']}>. Files are Git LFS objects; SHA-256 and size were",
        "checked against the LFS pointer published in the repo.",
        "",
        "Citation: Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building",
        "Data Genome Project 2, energy meter data from the ASHRAE Great Energy Predictor",
        "III competition. *Sci Data* 7, 368 (2020). https://doi.org/10.1038/s41597-020-00712-x",
        "",
        "| file | url | bytes | sha256 | verified |",
        "|---|---|---:|---|---|",
    ]
    lines += [f"| {n} | {u} | {s:,} | `{h}` | yes |" for n, u, s, h in rows]
    (RAW / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {RAW / 'SOURCES.md'}")


if __name__ == "__main__":
    main()
