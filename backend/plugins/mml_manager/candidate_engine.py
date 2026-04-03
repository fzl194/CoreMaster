# backend/plugins/mml_manager/candidate_engine.py
"""Candidate generation engine for MML dependency mining.

Implements:
- Value match aggregation with script-level dedup
- Multi-dimensional scoring (support, distinctiveness, order_consistency, name_relevance)
- Confidence calculation with configurable weights
"""
import json
from collections import defaultdict

# Default scoring weights
DEFAULT_WEIGHTS = {
    "support": 0.35,
    "distinctiveness": 0.35,
    "order_consistency": 0.20,
    "name_relevance": 0.10,
}

# Default confidence thresholds
THETA_HIGH = 0.85
THETA_LOW = 0.50

# Parameter name suffixes to strip for similarity comparison
_COMMON_SUFFIXES = ("NAME", "ID", "NO", "NUM", "TYPE", "VALUE", "ADDR", "IP")


def generate_candidates(
    command_instances_by_script: list[dict],
    weights: dict | None = None,
    theta_high: float = THETA_HIGH,
    theta_low: float = THETA_LOW,
) -> list[dict]:
    """Generate candidates from command instances grouped by script.

    Args:
        command_instances_by_script: list of {
            "file_entry_id": int,
            "ne_version_id": int,
            "commands": [{"operation", "name", "params": [{"name", "value"}], "line_number"}]
        }
        weights: scoring weights dict (optional)
        theta_high: high confidence threshold
        theta_low: low confidence threshold

    Returns:
        list of candidate dicts ready for database insertion.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    # accumulator key: (ref_cmd, ref_param, def_cmd, def_param)
    accumulator: dict[tuple, dict] = {}

    # Track which scripts contain which command pairs (for total_scripts)
    command_pair_scripts: dict[tuple, set] = defaultdict(set)

    for script in command_instances_by_script:
        file_id = script["file_entry_id"]
        commands = script["commands"]

        # Build command identifiers: "ADD APN" format
        cmd_ids = []
        for cmd in commands:
            cmd_key = f"{cmd['operation']} {cmd['name']}"
            cmd_ids.append((cmd_key, cmd))

        # Track command pair co-occurrence (unique command types per script)
        unique_cmd_keys = set(ck for ck, _ in cmd_ids)
        for ci in unique_cmd_keys:
            for cj in unique_cmd_keys:
                if ci != cj:
                    command_pair_scripts[(ci, cj)].add(file_id)

        # Find value matches: def before ref (i < j)
        for i in range(len(cmd_ids)):
            for j in range(i + 1, len(cmd_ids)):
                def_cmd_key, cmd_i = cmd_ids[i]
                ref_cmd_key, cmd_j = cmd_ids[j]

                for param_i in cmd_i["params"]:
                    for param_j in cmd_j["params"]:
                        val_i = param_i.get("value")
                        val_j = param_j.get("value")

                        # Filter null and empty
                        if not val_i or not val_j:
                            continue
                        if val_i != val_j:
                            continue

                        key = (ref_cmd_key, param_j["name"], def_cmd_key, param_i["name"])

                        # Skip self-referential candidates (same command + same param)
                        if ref_cmd_key == def_cmd_key and param_j["name"] == param_i["name"]:
                            continue

                        if key not in accumulator:
                            accumulator[key] = {
                                "script_ids": set(),
                                "values": set(),
                                "sample_lines": [],
                            }
                        accumulator[key]["script_ids"].add(file_id)
                        accumulator[key]["values"].add(val_i)
                        if len(accumulator[key]["sample_lines"]) < 5:
                            accumulator[key]["sample_lines"].append(
                                (cmd_i.get("line_number"), cmd_j.get("line_number"))
                            )

    # Build candidates from accumulator
    candidates = []
    for key, data in accumulator.items():
        ref_cmd, ref_param, def_cmd, def_param = key
        cmd_pair_key = (ref_cmd, def_cmd)
        total_scripts = len(command_pair_scripts.get(cmd_pair_key, set()))
        if total_scripts == 0:
            total_scripts = len(data["script_ids"])

        hit_count = len(data["script_ids"])
        unique_values = len(data["values"])

        scores = _calculate_scores(
            hit_count=hit_count,
            total_scripts=total_scripts,
            unique_values=unique_values,
            values=data["values"],
            sample_lines=data["sample_lines"],
            ref_param=ref_param,
            def_param=def_param,
            weights=weights,
        )

        confidence = scores["confidence"]

        # Determine initial status
        if confidence >= theta_high:
            status = "auto_passed"
        elif confidence >= theta_low:
            status = "llm_review"
        else:
            status = "man_review"

        # Build sample_scripts
        sample_lines = data["sample_lines"][:5]
        sample_scripts = []
        for line_def, line_ref in sample_lines:
            sample_scripts.append({
                "def_line": line_def,
                "ref_line": line_ref,
            })

        # Build counter_examples
        hit_file_ids = data["script_ids"]
        cooccur_ids = command_pair_scripts.get(cmd_pair_key, set())
        counter_ids = cooccur_ids - hit_file_ids
        counter_examples = []
        for cid in list(counter_ids)[:5]:
            counter_examples.append({
                "file_entry_id": cid,
                "reason": "两命令共现但参数值无匹配",
            })

        candidates.append({
            "ref_command": ref_cmd,
            "ref_param": ref_param,
            "def_command": def_cmd,
            "def_param": def_param,
            "status": status,
            "confidence": round(confidence, 4),
            "scores": {
                "support": round(scores["support"], 4),
                "distinctiveness": round(scores["distinctiveness"], 4),
                "order_consistency": round(scores["order_consistency"], 4),
                "name_relevance": round(scores["name_relevance"], 4),
            },
            "evidence": {
                "hit_count": hit_count,
                "hit_file_count": hit_count,
                "total_mined_files": total_scripts,
                "hit_values": sorted(data["values"]),
                "sample_scripts": sample_scripts,
            },
        })

    # Sort by confidence descending
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def generate_single_file_candidates(
    script: dict,
    weights: dict | None = None,
) -> list[dict]:
    """Generate contribution-level candidates from a single script file.

    This produces per-file contributions that can later be aggregated via
    ``aggregate_contributions``.  Each result represents what this one file
    contributes to the candidate pool — *not* a final aggregated candidate.

    Args:
        script: dict with keys ``file_entry_id``, ``ne_version_id``,
            ``commands`` (list of command dicts having ``operation``,
            ``name``, ``params``, ``line_number``).
        weights: optional scoring weights dict.

    Returns:
        list of contribution dicts with ``file_entry_id``, ``ne_version_id``,
        ref/def command/param identifiers, ``evidence``, and ``scores``.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    file_id = script["file_entry_id"]
    ne_version_id = script["ne_version_id"]
    commands = script["commands"]

    # Build command identifiers: "ADD APN" format
    cmd_ids = []
    for cmd in commands:
        cmd_key = f"{cmd['operation']} {cmd['name']}"
        cmd_ids.append((cmd_key, cmd))

    # Find value matches: def before ref (i < j) — same pairing logic as
    # generate_candidates but scoped to a single file.
    # Accumulate by key so multiple hits within the same file are merged.
    by_key: dict[tuple, dict] = {}

    for i in range(len(cmd_ids)):
        for j in range(i + 1, len(cmd_ids)):
            def_cmd_key, cmd_i = cmd_ids[i]
            ref_cmd_key, cmd_j = cmd_ids[j]

            for param_i in cmd_i["params"]:
                for param_j in cmd_j["params"]:
                    val_i = param_i.get("value")
                    val_j = param_j.get("value")

                    # Filter null and empty
                    if not val_i or not val_j:
                        continue
                    if val_i != val_j:
                        continue

                    key = (ref_cmd_key, param_j["name"], def_cmd_key, param_i["name"])

                    # Skip self-referential candidates (same command + same param)
                    if ref_cmd_key == def_cmd_key and param_j["name"] == param_i["name"]:
                        continue

                    if key not in by_key:
                        by_key[key] = {
                            "hit_values": set(),
                            "hit_count": 0,
                            "sample_scripts": [],
                        }
                    by_key[key]["hit_values"].add(val_i)
                    by_key[key]["hit_count"] += 1
                    if len(by_key[key]["sample_scripts"]) < 10:
                        by_key[key]["sample_scripts"].append({
                            "def_line": cmd_i.get("line_number"),
                            "ref_line": cmd_j.get("line_number"),
                        })

    # Build results from accumulated data
    results: list[dict] = []
    for key, data in by_key.items():
        hit_count = data["hit_count"]
        unique_values = len(data["hit_values"])

        scores = _calculate_scores(
            hit_count=hit_count,
            total_scripts=1,
            unique_values=unique_values,
            values=data["hit_values"],
            sample_lines=[(s["def_line"], s["ref_line"]) for s in data["sample_scripts"]],
            ref_param=key[1],
            def_param=key[3],
            weights=weights,
        )

        results.append({
            "file_entry_id": file_id,
            "ne_version_id": ne_version_id,
            "ref_command": key[0],
            "ref_param": key[1],
            "def_command": key[2],
            "def_param": key[3],
            "evidence": {
                "hit_count": hit_count,
                "hit_values": sorted(data["hit_values"]),
                "sample_scripts": data["sample_scripts"],
            },
            "scores": scores,
        })

    return results


def aggregate_contributions(
    contributions: list[dict],
    weights: dict | None = None,
) -> dict:
    """Aggregate per-file contributions into a single scored result.

    Each contribution dict is expected to have the following keys:

    * ``has_hit`` (bool)
    * ``hit_values`` (list of matched value strings)
    * ``order_consistency`` (float)
    * ``name_relevance`` (float)
    * ``hit_count`` (int)
    * ``confidence`` (float)
    * ``sample_scripts`` (list)

    Returns a dict with ``support``, ``distinctiveness``,
    ``order_consistency``, ``name_relevance`` and ``confidence``.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    if not contributions:
        return {
            "support": 0.0,
            "distinctiveness": 0.0,
            "order_consistency": 0.0,
            "name_relevance": 0.0,
            "confidence": 0.0,
        }

    total_files = len(contributions)
    hit_files = sum(1 for c in contributions if c.get("has_hit"))

    # Collect all values across contributions
    all_values: list[str] = []
    for c in contributions:
        all_values.extend(c.get("hit_values", []))
    unique_values = len(set(all_values))
    total_values = len(all_values)

    # Mean of per-file metrics
    order_consistency = (
        sum(c.get("order_consistency", 0.0) for c in contributions) / total_files
    )
    name_relevance = (
        sum(c.get("name_relevance", 0.0) for c in contributions) / total_files
    )

    support = hit_files / total_files if total_files > 0 else 0.0
    distinctiveness = unique_values / total_values if total_values > 0 else 0.0

    confidence = (
        weights["support"] * support
        + weights["distinctiveness"] * distinctiveness
        + weights["order_consistency"] * order_consistency
        + weights["name_relevance"] * name_relevance
    )

    return {
        "support": support,
        "distinctiveness": distinctiveness,
        "order_consistency": order_consistency,
        "name_relevance": name_relevance,
        "confidence": confidence,
    }


def _calculate_scores(
    hit_count: int,
    total_scripts: int,
    unique_values: int,
    values: set,
    sample_lines: list,
    ref_param: str,
    def_param: str,
    weights: dict,
) -> dict:
    """Calculate multi-dimensional scores for a candidate."""

    # Support: ratio of scripts with value match to total co-occurrence scripts
    support = hit_count / total_scripts if total_scripts > 0 else 0.0

    # Distinctiveness: ratio of unique values to total hits
    distinctiveness = unique_values / hit_count if hit_count > 0 else 0.0

    # Order consistency: fraction of lines where def comes before ref
    if sample_lines:
        consistent = sum(1 for d, r in sample_lines if d is not None and r is not None and d <= r)
        order_consistency = consistent / len(sample_lines)
    else:
        order_consistency = 1.0

    # Name relevance: similarity between param names
    name_relevance = _name_similarity(ref_param, def_param)

    confidence = (
        weights["support"] * support
        + weights["distinctiveness"] * distinctiveness
        + weights["order_consistency"] * order_consistency
        + weights["name_relevance"] * name_relevance
    )

    return {
        "support": support,
        "distinctiveness": distinctiveness,
        "order_consistency": order_consistency,
        "name_relevance": name_relevance,
        "confidence": confidence,
    }


def _name_similarity(name_a: str, name_b: str) -> float:
    """Calculate parameter name similarity (0.0-1.0)."""
    if not name_a or not name_b:
        return 0.0

    a = name_a.upper()
    b = name_b.upper()

    if a == b:
        return 1.0

    if a in b or b in a:
        return 0.8

    a_stripped = _strip_suffix(a)
    b_stripped = _strip_suffix(b)

    if a_stripped == b_stripped:
        return 0.9

    if a_stripped in b_stripped or b_stripped in a_stripped:
        return 0.7

    dist = _edit_distance(a_stripped, b_stripped)
    max_len = max(len(a_stripped), len(b_stripped))
    if max_len == 0:
        return 0.0
    similarity = 1.0 - (dist / max_len)
    return max(0.0, similarity)


def _strip_suffix(name: str) -> str:
    """Strip common parameter name suffixes."""
    for suffix in _COMMON_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]
