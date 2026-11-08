"""v1 路由汇总。新增模块时在此 include，保持 main.py 干净。"""
from fastapi import APIRouter

from app.api.v1 import system

api_router = APIRouter()
api_router.include_router(system.router)
