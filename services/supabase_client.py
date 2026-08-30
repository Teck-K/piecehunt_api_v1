from supabase import Client, create_client

from config import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


def get_client() -> Client:
    """Anon key client - genoeg om een token te verifiëren (auth.get_user)."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_client_as_user(access_token: str) -> Client:
    """Client die 'praat als' de ingelogde gebruiker - voor RLS-beveiligde queries."""
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(access_token)
    return client


def get_admin_client() -> Client:
    """Service_role client - alleen voor admin-only acties (bv. account verwijderen)."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
