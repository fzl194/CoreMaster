import json
import logging

from plugins.graph_mining.engine.scorers import aggregate_contributions

logger = logging.getLogger(__name__)


def _determine_review_route(confidence: float) -> str:
    if confidence >= 0.85:
        return "auto"
    elif confidence >= 0.50:
        return "llm"
    else:
        return "manual"


class CandidateService:
    """候选领域服务：汇总分数重算 + 终态保护（§6.6）"""

    def __init__(self, db):
        self.db = db

    async def get_total_mined(self, ne_version_id: int) -> int:
        rows = await self.db.query(
            "SELECT COUNT(DISTINCT file_entry_id) as cnt FROM file_mining_record "
            "WHERE ne_version_id=? AND mined=1",
            (ne_version_id,),
        )
        return rows[0]["cnt"] if rows else 0

    async def recalculate(self, cand_id: int, alg_ver: str, total_mined: int = 0) -> None:
        """重算候选汇总分数，遵守 §6.6 终态保护规则。

        从 mml_manager/main.py:1473-1609 的 _recalculate_candidate_scores 迁移。
        核心逻辑：
        1. 查询所有 contributions → 聚合分数
        2. graph/non_graph 状态：只更新分数和证据，不改变状态
        3. rejected 状态：新证据自动激活回 pending
        4. 同步 graph_edge 的 evidence（如果 candidate 在 graph 状态）
        """
        contribs = await self.db.query(
            "SELECT file_entry_id, scores_json, evidence_json FROM candidate_contribution "
            "WHERE candidate_id=? AND algorithm_version=?",
            (cand_id, alg_ver),
        )

        cand_rows = await self.db.query(
            "SELECT status, graph_edge_id, ne_version_id FROM dependency_candidate WHERE id=?",
            (cand_id,),
        )
        if not cand_rows:
            return
        cand = cand_rows[0]
        cand_status = cand["status"]

        # Zero contributions case
        if not contribs:
            if cand_status in ("graph", "rejected"):
                # Terminal state: clear scores but keep record
                zero_scores = json.dumps({
                    "support": 0.0, "distinctiveness": 0.0,
                    "order_consistency": 0.0, "name_relevance": 0.0,
                }, ensure_ascii=False)
                empty_evidence = json.dumps({}, ensure_ascii=False)
                await self.db.execute(
                    "UPDATE dependency_candidate SET confidence=0.0, scores_json=?, "
                    "evidence_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (zero_scores, empty_evidence, cand_id),
                )
                if cand_status == "graph" and cand["graph_edge_id"]:
                    await self.db.execute(
                        "UPDATE graph_edge SET evidence_json=?, confidence=0.0, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (empty_evidence, cand["graph_edge_id"]),
                    )
            elif cand_status == "pending":
                await self.db.execute(
                    "DELETE FROM dependency_candidate WHERE id=?", (cand_id,)
                )
            return

        # Get total mined files if not provided
        if total_mined <= 0:
            mined_rows = await self.db.query(
                "SELECT COUNT(DISTINCT file_entry_id) as cnt FROM file_mining_record "
                "WHERE ne_version_id=? AND mined=1",
                (cand["ne_version_id"],),
            )
            total_mined = mined_rows[0]["cnt"] if mined_rows else len(contribs)

        # Build contribution list
        hit_file_count = len(contribs)
        total_hit_count = 0
        contrib_list = []
        all_evidence = []
        per_file_data = []

        for c in contribs:
            scores = json.loads(c["scores_json"])
            evidence = json.loads(c["evidence_json"])
            hit_count = evidence.get("hit_count", 1)
            total_hit_count += hit_count
            contrib_list.append({
                "has_hit": True,
                "hit_values": evidence.get("hit_values", []),
                "order_consistency": scores.get("order_consistency", 0.0),
                "name_relevance": scores.get("name_relevance", 0.0),
                "hit_count": hit_count,
                "confidence": scores.get("confidence", 0.0),
                "sample_scripts": evidence.get("sample_scripts", []),
            })
            all_evidence.append(evidence)
            per_file_data.append({
                "file_entry_id": c["file_entry_id"],
                "hit_count": hit_count,
                "hit_values": evidence.get("hit_values", []),
                "sample_scripts": evidence.get("sample_scripts", []),
            })

        # No-hit placeholders for support denominator
        no_hit_count = max(0, total_mined - hit_file_count)
        for _ in range(no_hit_count):
            contrib_list.append({
                "has_hit": False, "hit_values": [], "order_consistency": 0.0,
                "name_relevance": 0.0, "hit_count": 0, "confidence": 0.0,
                "sample_scripts": [],
            })

        aggregated = aggregate_contributions(contrib_list)

        # Build new evidence
        all_values = set()
        for ev in all_evidence:
            vals = ev.get("hit_values", [])
            if isinstance(vals, (list, set)):
                all_values.update(vals)
            elif isinstance(vals, str):
                all_values.add(vals)

        all_scripts = []
        for pf in per_file_data:
            for s in pf["sample_scripts"]:
                all_scripts.append({"file_entry_id": pf["file_entry_id"], **s})

        new_evidence = {
            "hit_count": total_hit_count,
            "hit_file_count": hit_file_count,
            "total_mined_files": total_mined,
            "hit_values": sorted(all_values),
            "sample_scripts": all_scripts[:10],
            "per_file": per_file_data,
        }

        new_scores = {
            "support": aggregated["support"],
            "distinctiveness": aggregated["distinctiveness"],
            "order_consistency": aggregated["order_consistency"],
            "name_relevance": aggregated["name_relevance"],
        }

        new_confidence = aggregated["confidence"]
        scores_json = json.dumps(new_scores, ensure_ascii=False)
        evidence_json = json.dumps(new_evidence, ensure_ascii=False)

        # §6.6 Terminal state protection
        if cand_status in ("graph", "rejected"):
            # Terminal: only update scores/evidence, don't change status
            await self.db.execute(
                "UPDATE dependency_candidate SET confidence=?, scores_json=?, evidence_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_confidence, scores_json, evidence_json, cand_id),
            )
        else:
            # pending: normal update with review_route
            review_route = _determine_review_route(new_confidence)
            await self.db.execute(
                "UPDATE dependency_candidate SET confidence=?, scores_json=?, evidence_json=?, "
                "review_route=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_confidence, scores_json, evidence_json, review_route, cand_id),
            )

        # Sync evidence to graph_edge if candidate is in graph status
        if cand_status == "graph" and cand["graph_edge_id"]:
            await self.db.execute(
                "UPDATE graph_edge SET evidence_json=?, confidence=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (evidence_json, new_confidence, cand["graph_edge_id"]),
            )
