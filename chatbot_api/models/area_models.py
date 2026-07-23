from pydantic import BaseModel, Field


class NearbyRequest(BaseModel):
    place_name: str = Field(min_length=1, max_length=255)
    radius_meters: int = Field(default=5000, ge=1, le=50000)
    top_k: int | None = Field(default=None, ge=1, le=100)


class NearbyPlace(BaseModel):
    place: str
    address: str
    distance_meters: int


class NearbyResponse(BaseModel):
    origin: str
    radius_meters: int
    total: int
    data: list[NearbyPlace]
