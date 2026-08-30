from fastapi import APIRouter, Depends

from dependencies import get_current_user
from services.supabase_client import get_admin_client

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.delete("/me")
def delete_own_account(user=Depends(get_current_user)):
    """
    Verwijdert het account van de ingelogde gebruiker.
    user.id komt gegarandeerd uit het geverifieerde token - nooit uit de request zelf.
    """
    admin_supabase = get_admin_client()
    admin_supabase.auth.admin.delete_user(user.id)
    return {"status": "deleted", "user_id": user.id}
