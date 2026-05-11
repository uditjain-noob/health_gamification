def score_parameter(value: float, ref_min: float, ref_max: float) -> int:
    range_width = ref_max - ref_min
    if range_width <= 0:
        return 70
    midpoint = (ref_min + ref_max) / 2
    half_range = range_width / 2

    if ref_min <= value <= ref_max:
        proximity = 1 - abs(value - midpoint) / half_range
        return round(70 + proximity * 30)
    else:
        deviation = max(value - ref_max, ref_min - value)
        return max(0, round(70 - (deviation / range_width) * 70))


def score_organ(params: list[dict], critical_params: set[str]) -> int:
    total_weight = 0
    weighted_sum = 0
    for p in params:
        readings = p.get("readings", [])
        if not readings:
            continue
        latest_value = readings[0]["value"]
        s = score_parameter(latest_value, p["ref_min"], p["ref_max"])
        weight = 2 if p["name"].upper() in critical_params else 1
        weighted_sum += s * weight
        total_weight += weight
    if total_weight == 0:
        return 70
    return round(weighted_sum / total_weight)


def score_overall(organ_scores: dict[str, int], organ_weights: dict[str, float]) -> int:
    total_weight = 0.0
    weighted_sum = 0.0
    for organ, score in organ_scores.items():
        w = organ_weights.get(organ, 0.0)
        weighted_sum += score * w
        total_weight += w
    if total_weight == 0:
        return 0
    return min(1000, round((weighted_sum / total_weight) * 10))


def get_rank(overall_score: int) -> str:
    if overall_score >= 950:
        return "Diamond"
    if overall_score >= 800:
        return "Platinum"
    if overall_score >= 600:
        return "Gold"
    if overall_score >= 400:
        return "Silver"
    return "Bronze"


def get_level(overall_score: int) -> int:
    bands = [(0, 400, 1), (400, 600, 5), (600, 800, 9), (800, 950, 13), (950, 1001, 17)]
    for low, high, base_level in bands:
        if low <= overall_score < high:
            band_width = high - low
            position = (overall_score - low) / band_width
            return min(base_level + 3, base_level + round(position * 3))
    return 20


def get_difficulty(value: float, ref_min: float, ref_max: float) -> str:
    range_width = ref_max - ref_min
    if range_width <= 0:
        return "Easy"
    deviation = max(0.0, value - ref_max, ref_min - value)
    pct = deviation / range_width
    if pct < 0.20:
        return "Easy"
    if pct < 0.50:
        return "Medium"
    return "Hard"


def get_xp_for_difficulty(difficulty: str) -> int:
    return {"Easy": 10, "Medium": 20, "Hard": 30}.get(difficulty, 10)
