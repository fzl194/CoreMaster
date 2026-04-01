import re
from pathlib import Path


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

    # ── Public API ──────────────────────────────────────────────────────────

    def parse_text(self, text: str) -> list[dict]:
        """解析 MML 文本，返回命令列表（向后兼容接口）。"""
        result = self.parse_text_with_report(text)
        return result["commands"]

    def parse_file(self, path: str) -> list[dict]:
        """解析 MML 文件，返回命令列表。"""
        text = Path(path).read_text(encoding="utf-8")
        return self.parse_text(text)

    def parse_text_with_report(self, text: str) -> dict:
        """解析 MML 文本，返回命令列表和解析报告。"""
        lines = self._preprocess(text)
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

        for raw_line in text.splitlines():
            line_no += 1
            stripped = raw_line.strip()

            # Skip empty lines and line comments
            if not stripped or stripped.startswith("//"):
                report["total_lines"] += 1
                report["skipped"] += 1
                continue

            # Accumulate into buffer
            if not buf:
                buf_start_line = line_no

            # Handle backslash continuation
            if stripped.endswith("\\"):
                buf += stripped[:-1] + " "
                continue

            buf += stripped

            report["total_lines"] += 1

            # Check if command is complete (ends with ;)
            if not buf.rstrip().endswith(";"):
                continue

            # Try to parse the accumulated buffer
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

        # Handle remaining buffer (command without trailing ;)
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

    def _preprocess(self, text: str) -> str:
        """Strip block comments /* ... */ from text."""
        return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

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
                # Escaped character — keep both chars
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
        # Strip outer double quotes (backward compat with original behavior)
        stripped = value.strip('"')
        return self._process_escapes(stripped)

    def _process_escapes(self, s: str) -> str:
        """Process escape sequences: \\\" -> \", \\\\ -> \\."""
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
