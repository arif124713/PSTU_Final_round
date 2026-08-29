from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.redis_client import get_redis
from app.services import agent_service

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class AgentChatBody(BaseModel):
    message: str
    session_id: str


@router.post("/chat")
async def agent_chat(
    body: AgentChatBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await agent_service.chat(db, redis, current_user, body.session_id, body.message)


@router.get("/history/{session_id}")
async def agent_history(session_id: str, current_user: User = Depends(get_current_user)):
    return {"session_id": session_id, "messages": agent_service.get_history(session_id)}
