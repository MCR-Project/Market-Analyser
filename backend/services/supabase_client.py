"""
Supabase client factory for backend scripts.

Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment - from a
local .env in dev (see .env.example), or from GitHub Actions secrets in CI.
The service role key is required: RLS is enabled on ticker/prices with no
public policies, so only the service role can read or write them.
"""

import os

from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)
