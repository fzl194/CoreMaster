import pytest


def test_same_parameter_rule_filters():
    from plugins.graph_mining.engine.hard_rules import SameParameterRule
    rule = SameParameterRule()
    # ref_param == def_param → 淘汰
    candidate = {"ref_cmd": "ADD APN", "ref_param": "APNNAME", "def_cmd": "ADD VPN", "def_param": "APNNAME"}
    assert rule.check(candidate) is False
    # 不同参数 → 通过
    candidate["def_param"] = "VPNNAME"
    assert rule.check(candidate) is True


def test_self_reference_rule_filters():
    from plugins.graph_mining.engine.hard_rules import SelfReferenceRule
    rule = SelfReferenceRule()
    # 完全相同命令+参数 → 淘汰
    candidate = {"ref_cmd": "ADD APN", "ref_param": "APNNAME", "def_cmd": "ADD APN", "def_param": "APNNAME"}
    assert rule.check(candidate) is False
    # 相同命令不同参数 → 通过
    candidate["def_param"] = "APNID"
    assert rule.check(candidate) is True


def test_pipeline_runs_rules_then_scorers():
    from plugins.graph_mining.engine.pipeline import MiningPipeline
    from plugins.graph_mining.engine.hard_rules import SameParameterRule

    pipeline = MiningPipeline(hard_rules=[SameParameterRule()])
    candidates = [
        {"ref_cmd": "A", "ref_param": "X", "def_cmd": "B", "def_param": "X"},  # 淘汰
        {"ref_cmd": "A", "ref_param": "X", "def_cmd": "B", "def_param": "Y"},  # 通过
    ]
    passed = pipeline.filter(candidates)
    assert len(passed) == 1
    assert passed[0]["def_param"] == "Y"
