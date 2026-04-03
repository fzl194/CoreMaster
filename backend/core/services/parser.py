import re
from pathlib import Path

# 编码探测优先级：UTF-8(含BOM) → GB18030(GBK/GB2312超集) → Latin-1(兜底)
_ENCODING_TRIES = ("utf-8-sig", "utf-8", "gb18030", "latin-1")


def read_text_auto(path: Path) -> str:
    """自动探测文件编码并读取文本内容。

    依次尝试 UTF-8(BOM) → UTF-8 → GB18030 → Latin-1，
    首个不抛 UnicodeDecodeError 的编码即为结果。
    """
    raw = path.read_bytes()
    for enc in _ENCODING_TRIES:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 永远成功，理论上不会到这里
    return raw.decode("latin-1")


def decode_bytes_auto(data: bytes) -> str:
    """自动探测 bytes 编码并解码。用于上传文件等场景。"""
    for enc in _ENCODING_TRIES:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1")


class ParserService:
    """MML 通用解析器

    支持：
    - 单行和多行命令（无分号续行、行尾反斜杠续行）
    - 引号感知的参数切分（引号内的逗号不作为分隔符）
    - 双引号和单引号
    - 转义字符（\" \\）
    - 块注释 /* ... */
    - 行注释 //
    - 解析结果分类（parsed / skipped / unrecognized）
    - 解析报告
    """

    _COMMAND_RE = re.compile(
        r"^\s*(ADD|MOD|DEL|RMV|SET|GET|LST|DSP|ACT|DEA|BLK|UBL|REG|DEREG)"
        r"\s+(\w+)\s*:\s*(.*?)\s*;\s*$",
        re.IGNORECASE,
    )

    _COMMAND_START_RE = re.compile(
        r"^\s*(ADD|MOD|DEL|RMV|SET|GET|LST|DSP|ACT|DEA|BLK|UBL|REG|DEREG)\s+\w+\s*:",
        re.IGNORECASE,
    )

    # ── Public API ──────────────────────────────────────────────────────────

    def parse_text(self, text: str) -> list[dict]:
        """解析 MML 文本，返回命令列表（向后兼容接口）。"""
        result = self.parse_text_with_report(text)
        return result["commands"]

    def parse_file(self, path: str) -> list[dict]:
        """解析 MML 文件，返回命令列表。自动探测文件编码。"""
        text = read_text_auto(Path(path))
        return self.parse_text(text)

    @staticmethod
    def _strip_block_comments(text: str) -> str:
        """Remove block comments /* ... */ while preserving quoted content."""
        result = []
        i = 0
        n = len(text)
        while i < n:
            # Track quote state
            if text[i] == '"':
                result.append(text[i])
                i += 1
                while i < n and text[i] != '"':
                    if text[i] == '\\' and i + 1 < n:
                        result.append(text[i])
                        result.append(text[i + 1])
                        i += 2
                    else:
                        result.append(text[i])
                        i += 1
                if i < n:
                    result.append(text[i])  # closing "
                    i += 1
                continue
            if text[i] == "'":
                result.append(text[i])
                i += 1
                while i < n and text[i] != "'":
                    if text[i] == '\\' and i + 1 < n:
                        result.append(text[i])
                        result.append(text[i + 1])
                        i += 2
                    else:
                        result.append(text[i])
                        i += 1
                if i < n:
                    result.append(text[i])  # closing '
                    i += 1
                continue
            # Check for block comment start
            if text[i] == '/' and i + 1 < n and text[i + 1] == '*':
                # Skip until */
                i += 2
                while i < n:
                    if text[i] == '*' and i + 1 < n and text[i + 1] == '/':
                        i += 2
                        break
                    i += 1
                continue
            result.append(text[i])
            i += 1
        return ''.join(result)

    def parse_text_with_report(self, text: str) -> dict:
        """解析 MML 文本，返回命令列表和解析报告。"""
        # Strip block comments first (quote-aware)
        text = self._strip_block_comments(text)

        commands = []
        report = {
            "total_lines": 0,
            "parsed": 0,
            "skipped": 0,
            "unrecognized": 0,
            "sample_unrecognized": [],
        }

        line_no = 0
        buf = ""
        buf_start_line = 0

        def flush_unrecognized():
            """Flush current buffer as unrecognized."""
            nonlocal buf
            if buf.strip():
                report["unrecognized"] += 1
                if len(report["sample_unrecognized"]) < 5:
                    report["sample_unrecognized"].append({
                        "line_number": buf_start_line,
                        "text": buf.strip()[:100],
                    })
                report["total_lines"] += 1
            buf = ""

        for raw_line in text.splitlines():
            line_no += 1
            stripped = raw_line.strip()

            # Skip empty lines and line comments
            if not stripped or stripped.startswith("//"):
                # If we were accumulating a multi-line command, flush it
                if buf:
                    flush_unrecognized()
                report["total_lines"] += 1
                report["skipped"] += 1
                continue

            # Handle backslash continuation
            if stripped.endswith("\\"):
                if not buf:
                    buf_start_line = line_no
                buf += stripped[:-1] + " "
                continue

            # Accumulate into buffer
            if not buf:
                buf_start_line = line_no
            buf += stripped

            # Check if this looks like a command start
            if not buf.rstrip().endswith(";"):
                # If buffer doesn't start with a command keyword, it's unrecognized
                if not self._COMMAND_START_RE.match(buf):
                    flush_unrecognized()
                # Otherwise continue accumulating (multi-line command)
                continue

            report["total_lines"] += 1

            # Buffer ends with ; — try to parse
            match = self._COMMAND_RE.match(buf.strip())
            if match:
                operation, name, params_str = match.groups()
                params = self._parse_params(params_str)
                commands.append({
                    "operation": operation.upper(),
                    "name": name.upper(),
                    "params": params,
                    "raw_text": buf.strip(),
                    "line_number": buf_start_line,
                })
                report["parsed"] += 1
            else:
                report["unrecognized"] += 1
                if len(report["sample_unrecognized"]) < 5:
                    report["sample_unrecognized"].append({
                        "line_number": buf_start_line,
                        "text": buf.strip()[:100],
                    })
            buf = ""

        # Handle remaining buffer (incomplete command without ;)
        if buf.strip():
            report["total_lines"] += 1
            report["unrecognized"] += 1
            if len(report["sample_unrecognized"]) < 5:
                report["sample_unrecognized"].append({
                    "line_number": buf_start_line,
                    "text": buf.strip()[:100],
                })

        return {"commands": commands, "report": report}

    # ── Internal ────────────────────────────────────────────────────────────

    def _parse_params(self, params_str: str) -> list[dict]:
        """引号感知的参数切分。

        在引号内的逗号不作为分隔符。支持双引号和单引号。
        处理转义字符 \" 和 \\。
        """
        if not params_str or not params_str.strip():
            return []

        tokens = self._split_params(params_str)
        params = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                key = key.strip()
                value = value.strip()
                value = self._unquote(value)
            else:
                key = token.strip().strip(";")
                value = None
            params.append({"name": key, "value": value})
        return params

    def _split_params(self, s: str) -> list[str]:
        """Split parameter string by commas, respecting quoted strings."""
        tokens = []
        current = []
        in_double = False
        in_single = False
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '\\' and i + 1 < len(s) and s[i + 1] in ('"', '\\'):
                current.append(ch)
                current.append(s[i + 1])
                i += 2
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                current.append(ch)
            elif ch == "'" and not in_double:
                in_single = not in_single
                current.append(ch)
            elif ch == ',' and not in_double and not in_single:
                tokens.append(''.join(current))
                current = []
            else:
                current.append(ch)
            i += 1
        if current:
            tokens.append(''.join(current))
        return tokens

    def _unquote(self, value: str) -> str:
        """Remove surrounding quotes and process escape sequences."""
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                inner = value[1:-1]
                return self._process_escapes(inner)
        stripped = value.strip('"')
        return self._process_escapes(stripped)

    def _process_escapes(self, s: str) -> str:
        """Process escape sequences: \\" -> ", \\\\ -> \\."""
        result = []
        i = 0
        while i < len(s):
            if s[i] == '\\' and i + 1 < len(s):
                next_ch = s[i + 1]
                if next_ch == '"':
                    result.append('"')
                    i += 2
                    continue
                elif next_ch == '\\':
                    result.append('\\')
                    i += 2
                    continue
            result.append(s[i])
            i += 1
        return ''.join(result)
