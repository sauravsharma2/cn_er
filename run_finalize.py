"""Artifact declaration: writes output/run_manifest.json describing the run outputs.

    python run_finalize.py
"""
import hashlib
import json
from datetime import datetime, timezone

import pandas as pd
import yaml

from utils import config


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def finalize():
    descriptor = yaml.safe_load((config.ROOT_DIR / "descriptor.yaml").read_text(encoding="utf-8"))
    artifacts = []
    for p in sorted(config.OUTPUT_DIR.glob("*.xlsx")):
        sheets = pd.read_excel(p, sheet_name=None)
        entries = {k: len(v) for k, v in sheets.items() if k.startswith("Entries")}
        flags = sheets.get("Flag Summary")
        artifacts.append({
            "file": p.name,
            "bytes": p.stat().st_size,
            "sha256": _sha256(p),
            "rows": sum(entries.values()),
            "sheets": entries,
            "flag_summary": dict(zip(flags["Flag"], flags["Rows"].astype(int))) if flags is not None else {},
        })

    manifest = {
        "project": config.PROJECT_NAME,
        "version": descriptor.get("version"),
        "finalized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "db_server": config.DB_SERVER,
            "db_database": config.DB_DATABASE,
            "translator": config.TRANSLATOR,
            "model": config.OLLAMA_MODEL if config.TRANSLATOR == "ollama" else config.MARIAN_MODEL,
            "cnloc_year": config.CNLOC_YEAR,
        },
        "artifacts": artifacts,
    }
    out = config.OUTPUT_DIR / "run_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest -> {out}")
    return manifest


if __name__ == "__main__":
    finalize()
