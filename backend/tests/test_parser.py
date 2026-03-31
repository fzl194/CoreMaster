from core.services.parser import ParserService


def test_parse_single_command():
    svc = ParserService()
    text = 'ADD APN: APN="test_apn", BINDVPN=ENABLE, VRFNAME="vpn";'
    result = svc.parse_text(text)
    assert len(result) == 1
    cmd = result[0]
    assert cmd["operation"] == "ADD"
    assert cmd["name"] == "APN"
    assert len(cmd["params"]) == 3
    assert cmd["params"][0]["name"] == "APN"
    assert cmd["params"][0]["value"] == "test_apn"
    assert cmd["params"][1]["name"] == "BINDVPN"
    assert cmd["params"][1]["value"] == "ENABLE"


def test_parse_multiple_commands():
    svc = ParserService()
    text = """
ADD APN: APN="apn1";
MOD APN: APN="apn2";
"""
    result = svc.parse_text(text)
    assert len(result) == 2
    assert result[0]["operation"] == "ADD"
    assert result[1]["operation"] == "MOD"


def test_skip_comments():
    svc = ParserService()
    text = """// this is a comment
ADD APN: APN="test";"""
    result = svc.parse_text(text)
    assert len(result) == 1


def test_skip_empty_lines():
    svc = ParserService()
    text = """

ADD APN: APN="test";

"""
    result = svc.parse_text(text)
    assert len(result) == 1


def test_parse_param_without_value():
    svc = ParserService()
    text = "ADD APN: APN;"
    result = svc.parse_text(text)
    assert len(result) == 1
    assert result[0]["params"][0]["name"] == "APN"
    assert result[0]["params"][0]["value"] is None


def test_parse_command_with_spaces():
    svc = ParserService()
    text = 'ADD  APN :  APN = "test" , BIND = ON ;'
    result = svc.parse_text(text)
    assert len(result) == 1
    assert result[0]["name"] == "APN"
    assert result[0]["params"][0]["value"] == "test"
