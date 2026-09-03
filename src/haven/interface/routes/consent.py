from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.consent import get_policy, has_consented, record_consent
from haven.interface.deps import get_current_user_id, get_db
from haven.interface.schemas.consent import (
    ConsentRequest,
    ConsentResponse,
    PolicyResponse,
)

router = APIRouter(prefix="/api/consent", tags=["consent"])


@router.get("/policy", response_model=PolicyResponse)
async def get_privacy_policy() -> PolicyResponse:
    text = await get_policy()
    return PolicyResponse(
        policy_version="0.0.1",
        disclaimer_text=text,
    )


@router.post("", response_model=ConsentResponse)
async def give_consent(
    body: ConsentRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ConsentResponse:
    client_ip = request.client.host if request.client else None
    await record_consent(
        session,
        user_id,
        body.policy_version,
        body.scope,
        ip_address=client_ip,
    )
    text = await get_policy()
    return ConsentResponse(
        policy_version=body.policy_version,
        consented=True,
        disclaimer_text=text,
    )


@router.get("", response_model=ConsentResponse)
async def check_consent(
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ConsentResponse:
    consented = await has_consented(session, user_id)
    text = await get_policy()
    return ConsentResponse(
        policy_version="0.0.1",
        consented=consented,
        disclaimer_text=text,
    )