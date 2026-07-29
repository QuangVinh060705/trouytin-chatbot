import math
import re
import unicodedata
from typing import Iterable, Optional

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .database import create_database_engine, get_database_schema


class AreaRecommendationBot:
    DEFAULT_RADIUS_METERS = 5000

    def __init__(
        self,
        places: Optional[Iterable[dict]] = None,
        engine: Engine | None = None,
        schema: str | None = None,
    ):
        self.engine = engine or create_database_engine()
        self.schema = schema or get_database_schema()
        self.places = (
            self._normalize_places(places)
            if places is not None
            else self._load_places_from_db()
        )

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        earth_radius_meters = 6371000
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(float(lat1)))
            * math.cos(math.radians(float(lat2)))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return earth_radius_meters * c

    @staticmethod
    def _get_value(row, *keys):
        for key in keys:
            if isinstance(row, dict) and row.get(key) is not None:
                return row[key]
        return None

    @classmethod
    def _normalize_places(cls, rows):
        places = []
        for row in rows:
            name = cls._get_value(
                row,
                "name",
                "place",
                "TEN_TOA_NHA",
            )
            lat = cls._get_value(row, "lat", "latitude", "VI_DO")
            lon = cls._get_value(row, "lon", "lng", "longitude", "KINH_DO")
            address = cls._get_value(row, "address", "DIA_CHI")
            if not name:
                continue
            places.append({
                "name": str(name).strip(),
                "address": str(address).strip() if address else "",
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            })
        return places

    def _load_places_from_db(self):
        sql = text("""
            SELECT
                "TEN_TOA_NHA",
                "DIA_CHI",
                "VI_DO",
                "KINH_DO"
            FROM "TOA_NHA"
            WHERE COALESCE("IS_DELETED", FALSE) = FALSE
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()

        return self._normalize_places(rows)

    @staticmethod
    def _normalize_text(value):
        text_value = str(value or "").strip().casefold().replace("đ", "d")
        text_value = "".join(
            char
            for char in unicodedata.normalize("NFD", text_value)
            if unicodedata.category(char) != "Mn"
        )
        return re.sub(r"[^a-z0-9]+", " ", text_value).strip()

    @classmethod
    def _match_score(cls, keyword, target):
        normalized_keyword = cls._normalize_text(keyword)
        normalized_target = cls._normalize_text(target)

        if not normalized_keyword or not normalized_target:
            return 0
        if normalized_keyword == normalized_target:
            return 100
        if normalized_keyword in normalized_target:
            return 95
        if len(normalized_target) >= 5 and normalized_target in normalized_keyword:
            return 90
        return max(
            fuzz.WRatio(normalized_keyword, normalized_target),
            fuzz.token_set_ratio(normalized_keyword, normalized_target),
        )

    def _find_place(self, place_name):
        matches = self.find_places(place_name, top_k=1)
        return matches[0] if matches else None

    def find_places(self, place_name, threshold=70, top_k=None):
        """Trả về mọi tòa có tên/địa chỉ khớp, ưu tiên kết quả chính xác nhất."""
        matches = []

        for place in self.places:
            score = max(
                self._match_score(place_name, place["name"]),
                self._match_score(place_name, place["address"]),
            )
            if score >= threshold:
                matches.append((score, place))

        matches.sort(key=lambda item: item[0], reverse=True)
        places = [place for _, place in matches]
        return places[:top_k] if top_k is not None else places

    def find_place(self, place_name):
        return self._find_place(place_name)

    @staticmethod
    def format_result(result):
        return f"{result['place']} ({result['address']}) - {result['distance_meters']} mét"

    def find_nearby(self, place_name, radius_meters=DEFAULT_RADIUS_METERS, top_k=None):
        origin = self._find_place(place_name)
        if origin is None or origin["lat"] is None or origin["lon"] is None:
            return []

        results = []
        for place in self.places:
            if place["lat"] is None or place["lon"] is None:
                continue
            if (
                place["name"] == origin["name"]
                and place["lat"] == origin["lat"]
                and place["lon"] == origin["lon"]
            ):
                continue

            distance_meters = int(round(self.haversine(
                origin["lat"], origin["lon"], place["lat"], place["lon"]
            )))
            if distance_meters <= radius_meters:
                results.append({
                    "place": place["name"],
                    "address": place["address"],
                    "distance_meters": distance_meters,
                })

        results.sort(key=lambda item: item["distance_meters"])
        return results[:top_k] if top_k is not None else results

    def recommend(self, place_name, radius_meters=DEFAULT_RADIUS_METERS, top_k=None):
        return [self.format_result(x) for x in self.find_nearby(place_name, radius_meters, top_k)]