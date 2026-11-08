"""v1 路由汇总。新增模块时在此 include，保持 main.py 干净。"""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    barcodes,
    batches,
    categories,
    files,
    ingredients,
    nutrition,
    system,
    units,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(categories.router)
api_router.include_router(units.unit_router)
api_router.include_router(units.loc_router)
api_router.include_router(nutrition.router)
api_router.include_router(files.router)
api_router.include_router(ingredients.router)
api_router.include_router(barcodes.router)
api_router.include_router(batches.router)
