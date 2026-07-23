from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_area_service
from models.area_models import NearbyRequest, NearbyResponse
from services.area_bot_service import AreaBotService

router = APIRouter(prefix="/api/areas", tags=["Area Bot"])


@router.post("/nearby", response_model=NearbyResponse)
def find_nearby(
    request: NearbyRequest,
    service: AreaBotService = Depends(get_area_service),
):
    try:
        results = service.find_nearby(
            place_name=request.place_name,
            radius_meters=request.radius_meters,
            top_k=request.top_k,
        )
        return NearbyResponse(
            origin=request.place_name,
            radius_meters=request.radius_meters,
            total=len(results),
            data=results,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi tìm khoảng cách: {exc}") from exc
