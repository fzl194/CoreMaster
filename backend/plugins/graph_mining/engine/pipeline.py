from typing import Protocol
from .hard_rules import HardRule


class MiningPipeline:
    """评估管线：铁律过滤 → 代码软打分 → 路由分流"""

    def __init__(self, hard_rules: list | None = None):
        self._rules = hard_rules or []

    def filter(self, candidates: list[dict]) -> list[dict]:
        """应用所有铁律规则，返回通过筛选的候选"""
        result = []
        for c in candidates:
            passed = all(rule.check(c) for rule in self._rules)
            if passed:
                result.append(c)
        return result
