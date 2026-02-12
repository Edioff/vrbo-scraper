"""Local JSON file storage for scraper results."""

import json
import time

from .config import VRBO_DATA_DIR
from .logger import log


class LocalDB:
    def __init__(self, source: str = "vrbo"):
        self.source = source
        self._targets = []
        self._next_target_id = 1
        self._results = []
        self._data_dir = VRBO_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def run_start(self) -> int:
        run_id = int(time.time())
        log("VRBO run_start", source=self.source, run_id=run_id)
        return run_id

    def run_end(self, run_id: int, success: bool, notes: str = ""):
        # Save all collected results to JSON
        output_file = self._data_dir / f"vrbo_results_{run_id}.json"
        output_file.write_text(
            json.dumps(self._results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log("VRBO run_end", source=self.source, run_id=run_id, success=success,
            results=len(self._results), output=str(output_file), notes=notes)

    def add_target(self, run_id, typ, clean_url, full_url):
        row = {
            "id": self._next_target_id,
            "run_id": run_id,
            "type": typ,
            "value": clean_url,
            "url": full_url or clean_url,
            "status": "queued",
        }
        self._targets.append(row)
        self._next_target_id += 1

    def list_targets(self, run_id, typ, status="queued"):
        return [r for r in self._targets if r["run_id"] == run_id and r["type"] == typ and r["status"] == status]

    def update_target_status(self, target_id, status):
        for row in self._targets:
            if row["id"] == target_id:
                row["status"] = status
                break

    def save_rental(self, run_id, unique_url, data, lat, lon):
        self._results.append({
            "url": unique_url,
            "latitude": lat,
            "longitude": lon,
            **data,
        })
