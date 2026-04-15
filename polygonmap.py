import json
import re
from pathlib import Path
from threading import Lock
from typing import Dict, List

_geo_data: Dict = {"type": "FeatureCollection", "features": []}
_lock = Lock()


def init_geo_data(file_path: str) -> None:
    """Load geojson once and cache it in memory."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    features = data.get("features", []) if isinstance(data, dict) else []
    with _lock:
        _geo_data["type"] = "FeatureCollection"
        _geo_data["features"] = features


def _tokenize(query: str) -> List[str]:
    if not query:
        return []
    cleaned = re.sub(r"\s+", " ", query.strip())
    if not cleaned:
        return []
    return [token for token in cleaned.split(" ") if token]


def get_polygon_result(dong_name: str) -> Dict:
    """Return FeatureCollection matched by ADM_NM against query tokens."""
    tokens = _tokenize(dong_name)
    if not tokens:
        return {"type": "FeatureCollection", "features": []}

    with _lock:
        features = list(_geo_data.get("features", []))

    matched = []
    for feature in features:
        props = feature.get("properties") or {}
        adm_nm = str(props.get("ADM_NM") or "").strip()
        if not adm_nm:
            continue

        if all(token in adm_nm for token in tokens) or adm_nm in dong_name:
            matched.append(feature)

    return {"type": "FeatureCollection", "features": matched}
