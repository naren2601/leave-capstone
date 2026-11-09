from fastapi import APIRouter, HTTPException

from leavedesk.api.auth import INVALID_LOGIN, create_access_token
from leavedesk.api.schemas import LoginIn, TokenOut
from leavedesk.api.state import State

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, state: State) -> TokenOut:
    account = state.users.authenticate(body.email, body.password)
    if account is None:
        # The same message for a wrong email and a wrong password.
        raise HTTPException(401, INVALID_LOGIN, headers={"WWW-Authenticate": "Bearer"})

    token = create_access_token(account.employee_id, account.role, state.settings)
    return TokenOut(access_token=token, expires_in=state.settings.access_token_minutes * 60)
