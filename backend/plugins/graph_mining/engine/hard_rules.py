from typing import Protocol


class HardRule(Protocol):
    def check(self, candidate: dict) -> bool: ...


class SameParameterRule:
    """ref_param 和 def_param 不能是同一个参数名"""
    def check(self, candidate: dict) -> bool:
        return candidate.get("ref_param") != candidate.get("def_param")


class SelfReferenceRule:
    """同一命令 + 同一参数 → 自引用，淘汰"""
    def check(self, candidate: dict) -> bool:
        if candidate.get("ref_cmd") != candidate.get("def_cmd"):
            return True
        return candidate.get("ref_param") != candidate.get("def_param")
