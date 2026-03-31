import re
from pathlib import Path


class ParserService:
    """MML 通用解析器"""

    # 匹配：操作类型 命令名 : 参数列表 ;
    _COMMAND_RE = re.compile(
        r"^\s*(ADD|MOD|DEL|RMV|SET|GET|LST|DSP|ACT|DEA|BLK|UBL|REG|DEREG)"
        r"\s+(\w+)\s*:\s*(.*?)\s*;\s*$",
        re.IGNORECASE,
    )

    def parse_text(self, text: str) -> list[dict]:
        results = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            match = self._COMMAND_RE.match(stripped)
            if not match:
                continue
            operation, name, params_str = match.groups()
            params = self._parse_params(params_str)
            results.append({
                "operation": operation.upper(),
                "name": name.upper(),
                "params": params,
                "raw_text": stripped,
                "line_number": line_no,
            })
        return results

    def parse_file(self, path: str) -> list[dict]:
        text = Path(path).read_text(encoding="utf-8")
        return self.parse_text(text)

    def _parse_params(self, params_str: str) -> list[dict]:
        if not params_str.strip():
            return []
        params = []
        for token in params_str.split(","):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                value = value.strip().strip('"')
            else:
                key = token.strip().strip(";")
                value = None
            params.append({"name": key.strip(), "value": value})
        return params
