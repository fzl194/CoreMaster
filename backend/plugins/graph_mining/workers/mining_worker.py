import json
import logging
from pathlib import Path

from core.services.parser import read_text_auto
from plugins.graph_mining.engine.scorers import generate_single_file_candidates
from plugins.graph_mining.services.candidate_service import _determine_review_route

logger = logging.getLogger(__name__)

_MML_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "mml_files"


def _json_serialize_evidence(evidence: dict) -> str:
    """Serialize evidence dict to JSON, converting sets to sorted lists."""
    clean = {}
    for k, v in evidence.items():
        if isinstance(v, set):
            clean[k] = sorted(v)
        elif isinstance(v, list):
            clean[k] = [
                {sk: (sorted(sv) if isinstance(sv, set) else sv) for sk, sv in item.items()}
                if isinstance(item, dict) else item
                for item in v
            ]
        else:
            clean[k] = v
    return json.dumps(clean, ensure_ascii=False)


def _safe_file_path(file_path: str | None) -> Path | None:
    """校验 file_path 是否位于 MML_STORAGE_ROOT 下，防止路径穿越。"""
    if not file_path:
        return None
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(_MML_STORAGE_ROOT):
        return None
    return resolved


class MiningWorker:
    """消费 mining 类型 job 的 worker handler"""

    def __init__(self, db, parser, job_service, candidate_service):
        self.db = db
        self.parser = parser
        self.job_service = job_service
        self.candidate_service = candidate_service

    async def handle(self, job: dict, items: list[dict]) -> dict:
        params = json.loads(job["params_json"])
        ne_version_id = params["ne_version_id"]
        alg_ver = "v1"

        all_cand_ids = set()
        mined_count = 0

        for item in items:
            # Check cancellation
            fresh_job = await self.job_service.get_job(job["id"])
            if fresh_job["status"] == "cancelled":
                break

            file_id = int(item["item_key"])
            await self.job_service.update_item_status(item["id"], "running")

            try:
                cand_ids = await self._mine_single_file(file_id, ne_version_id, alg_ver)
                all_cand_ids.update(cand_ids)
                await self.job_service.update_item_status(item["id"], "completed")
                await self.job_service.increment_progress(job["id"])
                mined_count += 1
            except Exception as e:
                logger.exception("Failed to mine file %d", file_id)
                await self.job_service.update_item_status(
                    item["id"], "failed", error_message=str(e)
                )

        # Recalculate all affected candidates via shared service
        total_mined = await self.candidate_service.get_total_mined(ne_version_id)
        for cand_id in all_cand_ids:
            await self.candidate_service.recalculate(cand_id, alg_ver, total_mined)

        return {"mined_files": mined_count, "candidates_affected": len(all_cand_ids)}

    async def _mine_single_file(self, file_id: int, ne_version_id: int, alg_ver: str) -> list[int]:
        """挖掘单个文件，返回受影响的 candidate IDs"""
        # 1. Query file entry
        entry_rows = await self.db.query(
            "SELECT id, name, file_path, ne_version_id FROM file_entry "
            "WHERE id=? AND type='file'",
            (file_id,),
        )
        if not entry_rows:
            return []
        entry = entry_rows[0]

        # 2. Read and parse file
        p = _safe_file_path(entry["file_path"])
        if p is None or not p.exists():
            return []
        content = read_text_auto(p)
        result = self.parser.parse_text_with_report(content)
        commands = result["commands"]

        # 3. Generate single-file candidates
        script = {
            "file_entry_id": file_id,
            "ne_version_id": ne_version_id,
            "commands": commands,
        }
        local_candidates = generate_single_file_candidates(script)

        # 4. Update file_mining_record
        await self.db.execute(
            "INSERT INTO file_mining_record (file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
            "VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT(file_entry_id) DO UPDATE SET "
            "mined=1, algorithm_version=?, command_count=?, updated_at=CURRENT_TIMESTAMP",
            (file_id, ne_version_id, alg_ver, len(commands), alg_ver, len(commands)),
        )

        # 5. Merge candidates
        affected_cand_ids = []
        for lc in local_candidates:
            cand_key = (lc["ref_command"], lc["ref_param"], lc["def_command"], lc["def_param"])
            confidence = lc["scores"]["confidence"]

            # Find existing candidate
            existing = await self.db.query(
                "SELECT id, status, active_algorithm_version FROM dependency_candidate "
                "WHERE ne_version_id=? AND ref_command=? AND ref_param=? "
                "AND def_command=? AND def_param=?",
                (ne_version_id, *cand_key),
            )

            if not existing:
                # Create new candidate
                review_route = _determine_review_route(confidence)
                scores_json = json.dumps(lc["scores"], ensure_ascii=False)
                evidence_json = _json_serialize_evidence(lc["evidence"])

                await self.db.execute(
                    "INSERT INTO dependency_candidate "
                    "(ne_version_id, ref_command, ref_param, def_command, def_param, "
                    "status, confidence, scores_json, evidence_json, "
                    "review_route, active_algorithm_version) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                    (ne_version_id, *cand_key, confidence,
                     scores_json, evidence_json, review_route, alg_ver),
                )
                existing = await self.db.query(
                    "SELECT id, status, active_algorithm_version FROM dependency_candidate "
                    "WHERE ne_version_id=? AND ref_command=? AND ref_param=? "
                    "AND def_command=? AND def_param=?",
                    (ne_version_id, *cand_key),
                )

            cand_row = existing[0]
            cand_id = cand_row["id"]

            # UPSERT contribution
            contrib_evidence = _json_serialize_evidence(lc["evidence"])
            contrib_scores = json.dumps(lc["scores"], ensure_ascii=False)
            await self.db.execute(
                "INSERT INTO candidate_contribution "
                "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(candidate_id, file_entry_id, algorithm_version) DO UPDATE SET "
                "evidence_json=?, scores_json=?, updated_at=CURRENT_TIMESTAMP",
                (cand_id, file_id, alg_ver, contrib_evidence, contrib_scores,
                 contrib_evidence, contrib_scores),
            )

            affected_cand_ids.append(cand_id)

        return affected_cand_ids
