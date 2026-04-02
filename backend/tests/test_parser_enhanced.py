# backend/tests/test_parser_enhanced.py
"""Comprehensive tests for the enhanced MML parser.

Covers: multi-line, quote-aware splitting, escape characters, block comments,
parse report, and backward compatibility.
"""
from core.services.parser import ParserService


def _svc():
    return ParserService()


# ── Backward Compatibility ────────────────────────────────────────────────


def test_single_command():
    svc = _svc()
    result = svc.parse_text('ADD APN: APN="test_apn", BINDVPN=ENABLE, VRFNAME="vpn";')
    assert len(result) == 1
    cmd = result[0]
    assert cmd["operation"] == "ADD"
    assert cmd["name"] == "APN"
    assert len(cmd["params"]) == 3
    assert cmd["params"][0]["name"] == "APN"
    assert cmd["params"][0]["value"] == "test_apn"
    assert cmd["params"][1]["name"] == "BINDVPN"
    assert cmd["params"][1]["value"] == "ENABLE"


def test_multiple_commands():
    svc = _svc()
    result = svc.parse_text('ADD APN: APN="apn1";\nMOD APN: APN="apn2";\n')
    assert len(result) == 2
    assert result[0]["operation"] == "ADD"
    assert result[1]["operation"] == "MOD"


def test_skip_comments():
    svc = _svc()
    result = svc.parse_text("// this is a comment\nADD APN: APN=\"test\";")
    assert len(result) == 1


def test_skip_empty_lines():
    svc = _svc()
    result = svc.parse_text("\n\nADD APN: APN=\"test\";\n\n")
    assert len(result) == 1


def test_param_without_value():
    svc = _svc()
    result = svc.parse_text("ADD APN: APN;")
    assert len(result) == 1
    assert result[0]["params"][0]["name"] == "APN"
    assert result[0]["params"][0]["value"] is None


def test_command_with_spaces():
    svc = _svc()
    result = svc.parse_text('ADD  APN :  APN = "test" , BIND = ON ;')
    assert len(result) == 1
    assert result[0]["name"] == "APN"
    assert result[0]["params"][0]["value"] == "test"


# ── Multi-line Commands ───────────────────────────────────────────────────


def test_multiline_command_no_semicolon():
    """Lines without trailing semicolon are joined with the next line."""
    svc = _svc()
    text = 'ADD APN: APN="test"\n    , VRFNAME="vpn";\n'
    result = svc.parse_text(text)
    assert len(result) == 1
    assert result[0]["operation"] == "ADD"
    assert result[0]["name"] == "APN"
    assert len(result[0]["params"]) == 2
    assert result[0]["params"][1]["name"] == "VRFNAME"
    assert result[0]["params"][1]["value"] == "vpn"


def test_multiline_command_backslash():
    """Lines ending with backslash continue on next line."""
    svc = _svc()
    text = 'ADD APN: APN="test" \\\n    , VRFNAME="vpn";\n'
    result = svc.parse_text(text)
    assert len(result) == 1
    assert len(result[0]["params"]) == 2


def test_multiple_multiline_commands():
    """Several multi-line commands in sequence."""
    svc = _svc()
    text = (
        'ADD VPN: VPN="vpn1"\n    , DESC="first";\n'
        'ADD APN: APN="apn1"\n    , VRFNAME="vpn1";\n'
    )
    result = svc.parse_text(text)
    assert len(result) == 2
    assert result[0]["name"] == "VPN"
    assert result[1]["name"] == "APN"


# ── Quote-aware Splitting ─────────────────────────────────────────────────


def test_value_with_comma_in_double_quotes():
    """Commas inside double quotes should not split parameters."""
    svc = _svc()
    result = svc.parse_text('ADD APN: APN="test", DESC="a,b,c";')
    assert len(result) == 1
    assert len(result[0]["params"]) == 2
    assert result[0]["params"][1]["name"] == "DESC"
    assert result[0]["params"][1]["value"] == "a,b,c"


def test_value_with_single_quotes():
    """Single-quoted values are preserved."""
    svc = _svc()
    result = svc.parse_text("ADD APN: APN='has space', DESC='ok';")
    assert len(result) == 1
    assert result[0]["params"][0]["value"] == "has space"


def test_mixed_quotes():
    """Mix of double and single quoted values."""
    svc = _svc()
    result = svc.parse_text('ADD APN: APN="val1", NAME=\'val2\';')
    assert len(result) == 1
    assert result[0]["params"][0]["value"] == "val1"
    assert result[0]["params"][1]["value"] == "val2"


# ── Escape Characters ─────────────────────────────────────────────────────


def test_escaped_quote_in_value():
    r"""Escaped double quote inside double-quoted value: DESC="say \"hello\"". """
    svc = _svc()
    result = svc.parse_text(r'ADD APN: APN="test", DESC="say \"hello\"";')
    assert len(result) == 1
    desc_val = result[0]["params"][1]["value"]
    assert desc_val == 'say "hello"'


def test_escaped_backslash():
    r"""Escaped backslash: PATH="C:\\Users"."""
    svc = _svc()
    result = svc.parse_text(r'ADD APN: APN="test", PATH="C:\\Users";')
    assert len(result) == 1
    path_val = result[0]["params"][1]["value"]
    assert path_val == r"C:\Users"


# ── Block Comments ────────────────────────────────────────────────────────


def test_block_comment():
    """/* ... */ block comments are stripped."""
    svc = _svc()
    text = '/* this is a comment */\nADD APN: APN="test";\n'
    result = svc.parse_text(text)
    assert len(result) == 1


def test_multiline_block_comment():
    """Multi-line block comments are stripped."""
    svc = _svc()
    text = '/* line1\nline2\nline3 */\nADD APN: APN="test";\n'
    result = svc.parse_text(text)
    assert len(result) == 1


def test_inline_block_comment():
    """Inline block comment within a line."""
    svc = _svc()
    text = 'ADD APN: APN="test" /* inline */ ;\n'
    result = svc.parse_text(text)
    assert len(result) == 1


# ── Parse Report ──────────────────────────────────────────────────────────


def test_parse_report_counts():
    """Verify report has correct total_lines, parsed, skipped, unrecognized."""
    svc = _svc()
    text = (
        '// comment\n'
        '\n'
        'ADD APN: APN="test";\n'
        'MOD APN: APN="ok";\n'
        'this is garbage\n'
        'GARBAGE LINE HERE\n'
    )
    result = svc.parse_text_with_report(text)
    report = result["report"]
    assert report["parsed"] == 2
    assert report["skipped"] == 2  # comment + empty
    assert report["unrecognized"] == 2
    assert report["total_lines"] == 6
    assert len(report["sample_unrecognized"]) == 2


def test_parse_report_sample_unrecognized():
    """Unrecognized line samples should contain line number and text."""
    svc = _svc()
    text = 'ADD APN: APN="ok";\nNOT A COMMAND\n'
    result = svc.parse_text_with_report(text)
    samples = result["report"]["sample_unrecognized"]
    assert len(samples) == 1
    assert samples[0]["line_number"] == 2
    assert "NOT A COMMAND" in samples[0]["text"]


def test_parse_report_max_five_samples():
    """At most 5 unrecognized samples."""
    svc = _svc()
    lines = [f"garbage line {i}" for i in range(10)]
    text = "\n".join(lines)
    result = svc.parse_text_with_report(text)
    assert len(result["report"]["sample_unrecognized"]) == 5


def test_parse_text_backward_compat():
    """parse_text() returns list[dict] same shape as before."""
    svc = _svc()
    text = 'ADD APN: APN="test", VRFNAME="vpn";\n'
    result = svc.parse_text(text)
    assert isinstance(result, list)
    assert len(result) == 1
    assert "operation" in result[0]
    assert "name" in result[0]
    assert "params" in result[0]
    assert "line_number" in result[0]


def test_block_comment_inside_double_quotes_preserved():
    """Block comment pattern inside double-quoted value must NOT be stripped."""
    svc = _svc()
    text = 'ADD APN: DESC="keep /* not comment */ text", APN="x";\n'
    result = svc.parse_text(text)
    assert len(result) == 1
    desc_val = result[0]["params"][0]["value"]
    assert desc_val == "keep /* not comment */ text"


def test_block_comment_inside_single_quotes_preserved():
    """Block comment pattern inside single-quoted value must NOT be stripped."""
    svc = _svc()
    text = "ADD APN: DESC='keep /* not comment */ text', APN='x';\n"
    result = svc.parse_text(text)
    assert len(result) == 1
    desc_val = result[0]["params"][0]["value"]
    assert desc_val == "keep /* not comment */ text"


def test_block_comment_mixed_with_quoted_values():
    """Real block comment stripped, but quoted /* ... */ preserved."""
    svc = _svc()
    text = '/* header comment */\nADD APN: DESC="keep /* inner */ ok", APN="x";\n'
    result = svc.parse_text(text)
    assert len(result) == 1
    desc_val = result[0]["params"][0]["value"]
    assert desc_val == "keep /* inner */ ok"


def test_parse_report_with_multiline():
    """Multi-line command counts as 2 total_lines but 1 parsed."""
    svc = _svc()
    text = 'ADD APN: APN="test"\n    , VRFNAME="vpn";\n'
    result = svc.parse_text_with_report(text)
    report = result["report"]
    assert report["parsed"] == 1
    # Both lines are consumed; second line joins the first
    assert report["total_lines"] == 2 or report["total_lines"] == 1
