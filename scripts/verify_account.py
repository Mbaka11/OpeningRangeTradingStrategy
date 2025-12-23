"""
Script to verify OANDA account connection, currency, and margin.
Usage: python scripts/verify_account.py
"""
import sys
from pathlib import Path

# Add project root to path so we can import live modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from live import broker_oanda
from live.config import OANDA_ACCOUNT_ID, OANDA_ENV

def main():
    print(f"--- OANDA Account Verification ---")
    print(f"Environment: {OANDA_ENV}")
    print(f"Account ID:  {OANDA_ACCOUNT_ID}")
    
    try:
        summary = broker_oanda.get_account_summary()
        print("\n[SUCCESS] Account Connected:")
        print(f"  Currency:     {summary.get('currency')}")
        print(f"  Balance:      {summary.get('balance'):,.2f}")
        print(f"  NAV:          {summary.get('nav'):,.2f}")
        print(f"  Margin Avail: {summary.get('margin_available'):,.2f}")
        
        if summary.get('currency') != 'USD':
            print("\n[WARNING] Currency is NOT USD. Please check your .env file.")
        
        # Check roughly for 80 units of NAS100 (approx $102k margin needed)
        if summary.get('margin_available', 0) < 105000:
             print("\n[WARNING] Margin available is below $105k. 80 units of NAS100 requires ~$102k.")
        else:
             print("\n[OK] Sufficient margin for 80 units strategy.")

    except Exception as e:
        print(f"\n[ERROR] Could not fetch account summary: {e}")

if __name__ == "__main__":
    main()