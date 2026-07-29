import math
import os
from typing import Iterable, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv()


class AreaRecommendationBot:
    DEFAULT_RADIUS_METERS = 5000

    def __init__(self, places: Optional[Iterable[dict]] = None, conn=None):
        self.conn = conn
        self.places = self._normalize_places(places) if places is not None else self._load_places_from_db()

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        """Tính khoảng cách giữa 2 tọa độ theo mét."""
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
            name = cls._get_value(row, "name", "place", "TEN_TOA_NHA", "DIA_CHI")
            lat = cls._get_value(row, "lat", "latitude", "LATITUDE")
            lon = cls._get_value(row, "lon", "lng", "longitude", "LONGITUDE")
            address = cls._get_value(row, "address", "DIA_CHI")

            if not name or lat is None or lon is None:
                continue

            places.append(
                {
                    "name": str(name).strip(),
                    "address": str(address).strip() if address else "",
                    "lat": float(lat),
                    "lon": float(lon),
                }
            )

        return places

    def _connect(self):
        import pymysql

        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", "2005"),
            database=os.getenv("MYSQL_DATABASE", "apartment_management_dev"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _load_places_from_db(self):
        sql = """
        SELECT 
            TEN_TOA_NHA, 
            DIA_CHI, 
            LATITUDE, 
            LONGITUDE 
        FROM TOA_NHA
        WHERE LATITUDE IS NOT NULL 
          AND LONGITUDE IS NOT NULL
        """

        close_conn = False
        if self.conn is None:
            self.conn = self._connect()
            close_conn = True

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
        finally:
            if close_conn:
                self.conn.close()
                self.conn = None

        return self._normalize_places(rows)

    @staticmethod
    def _match_text(keyword, target):
        return str(keyword).strip().casefold() in str(target).strip().casefold()

    def _find_place(self, place_name):
        for place in self.places:
            if self._match_text(place_name, place["name"]) or (
                place["address"] and self._match_text(place_name, place["address"])
            ):
                return place
        return None

    @staticmethod
    def format_result(result):
        return f"{result['place']} ({result['address']}) - {result['distance_meters']} mét"

    def find_nearby(self, place_name, radius_meters=DEFAULT_RADIUS_METERS, top_k=None):
        origin = self._find_place(place_name)
        
        # Nếu không tìm thấy, trả về rỗng một cách im lặng
        if origin is None:
            return []

        results = []
        for place in self.places:
            if place["name"] == origin["name"] and place["lat"] == origin["lat"] and place["lon"] == origin["lon"]:
                continue

            distance = self.haversine(origin["lat"], origin["lon"], place["lat"], place["lon"])
            distance_meters = int(round(distance))

            if distance_meters <= radius_meters:
                results.append(
                    {
                        "place": place["name"],
                        "address": place["address"],
                        "distance_meters": distance_meters,
                    }
                )

        results.sort(key=lambda item: item["distance_meters"])

        if top_k is not None:
            return results[:top_k]
        return results

    def recommend(self, place_name, radius_meters=DEFAULT_RADIUS_METERS, top_k=None):
        return [self.format_result(result) for result in self.find_nearby(place_name, radius_meters, top_k)]


if __name__ == "__main__":
    bot = AreaRecommendationBot()
    
    place = input("Nhập tên tòa nhà hoặc địa chỉ cần tìm xung quanh: ").strip()
    if place:
        results = bot.recommend(place)
        if results:
            print(f"\n--- Các địa điểm trong bán kính 5000m gần nhất ---")
            for line in results:
                print(f"[+] {line}")
        else:
            print("Không tìm thấy tòa nhà nào khác trong bán kính 5000m.")