from core.area_bot import AreaRecommendationBot


class AreaBotService:
    """Service chuyên xử lý tìm các tòa nhà trong bán kính cho trước."""

    def __init__(self, bot: AreaRecommendationBot | None = None):
        self.bot = bot or AreaRecommendationBot()

    def find_nearby(
        self,
        place_name: str,
        radius_meters: int = AreaRecommendationBot.DEFAULT_RADIUS_METERS,
        top_k: int | None = None,
    ) -> list[dict]:
        return self.bot.find_nearby(
            place_name=place_name,
            radius_meters=radius_meters,
            top_k=top_k,
        )
