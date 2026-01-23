"""
Script to list all OANDA accounts accessible with the current API Token.
Usage: python scripts/list_accounts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.trading import broker_oanda
from services.trading.config import OANDA_ENV

def main():
    print(f"--- OANDA Account List ({OANDA_ENV}) ---")
    try:
        data = broker_oanda.get_accounts()
        accounts = data.get("accounts", [])
        print(f"Token is VALID. Found {len(accounts)} accounts:")
        for acc in accounts:
            print(f" - ID: {acc['id']} | Tags: {acc.get('tags', [])}")
        
        print("\nCheck if your .env OANDA_ACCOUNT_ID matches one of these exactly.")
    except Exception as e:
        print(f"[ERROR] Failed to list accounts. Your Token might be invalid or wrong Environment.")
        print(f"Error details: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Server message: {e.response.text}")

if __name__ == "__main__":
    main()