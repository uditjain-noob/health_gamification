import json
import re


def _parse_range_string(range_str: str) -> tuple[float, float, str]:
    s = re.sub(r"^[Rr]ange\s*", "", range_str.strip())
    m = re.match(r"([\d.]+)\s*[-–]\s*([\d.]+)\s*(.*)", s)
    if not m:
        return 0.0, 0.0, ""
    return float(m.group(1)), float(m.group(2)), m.group(3).strip()


def compute_status(value: float, ref_min: float, ref_max: float) -> str:
    if value < ref_min:
        return "low"
    if value > ref_max:
        return "high"
    return "normal"


def _detect_format(item: dict) -> str:
    has_param = "parameter" in item
    has_param_values = "parameterValues" in item
    has_range_str = "range" in item and isinstance(item.get("range"), str)
    if has_param and has_param_values and has_range_str:
        return "sample"
    has_name = "name" in item or "parameter" in item
    has_readings = "readings" in item
    has_ref = "reference_min" in item or "ref_min" in item
    if has_name and has_readings and has_ref:
        return "simple"
    return "unknown"


def _normalize_sample(item: dict) -> dict:
    ref_min, ref_max, unit = _parse_range_string(item.get("range", "0 - 0"))
    readings = []
    for pv in item.get("parameterValues", []):
        date_str = pv.get("resultDate", "")[:10]
        readings.append({
            "date": date_str,
            "value": float(pv.get("value", 0)),
            "status": compute_status(float(pv.get("value", 0)), ref_min, ref_max)
        })
    return {
        "name": item["parameter"],
        "unit": unit,
        "ref_min": ref_min,
        "ref_max": ref_max,
        "readings": readings,
    }


def _normalize_simple(item: dict) -> dict:
    ref_min = float(item.get("ref_min", item.get("reference_min", 0)))
    ref_max = float(item.get("ref_max", item.get("reference_max", 0)))
    readings = []
    for r in item.get("readings", []):
        v = float(r.get("value", 0))
        readings.append({
            "date": r.get("date", ""),
            "value": v,
            "status": compute_status(v, ref_min, ref_max),
        })
    return {
        "name": item.get("name", item.get("parameter", "")),
        "unit": item.get("unit", ""),
        "ref_min": ref_min,
        "ref_max": ref_max,
        "readings": readings,
    }


_LLM_NORMALIZE_PROMPT = """Convert the following lab data JSON to this exact schema and return ONLY valid JSON, no explanation:
[{{"name": str, "unit": str, "ref_min": float, "ref_max": float, "readings": [{{"date": "YYYY-MM-DD", "value": float}}]}}]

Input:
{data}"""


class Parser:
    def __init__(self, llm_client=None):
        self._llm = llm_client

    def parse_json(self, data: list[dict]) -> list[dict]:
        if not data:
            return []
        fmt = _detect_format(data[0])
        if fmt == "sample":
            return [_normalize_sample(item) for item in data]
        if fmt == "simple":
            return [_normalize_simple(item) for item in data]
        if self._llm is None:
            raise ValueError("Unknown JSON format and no LLM client provided for fallback normalization")
        raw = self._llm.complete(
            system="You are a data normalization assistant.",
            user=_LLM_NORMALIZE_PROMPT.format(data=json.dumps(data))
        )
        try:
            normalized = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}") from e
        return [_normalize_simple(item) for item in normalized]

    def parse_pdf(self, file_path: str) -> list[dict]:
        import pdfplumber
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        prompt = f"""Extract all lab test parameters from this lab report text and return ONLY valid JSON:
[{{"name": str, "unit": str, "ref_min": float, "ref_max": float, "readings": [{{"date": "YYYY-MM-DD", "value": float}}]}}]

Lab report text:
{text}"""
        raw = self._llm.complete(system="You are a medical data extraction assistant.", user=prompt)
        try:
            normalized = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}") from e
        return [_normalize_simple(item) for item in normalized]
