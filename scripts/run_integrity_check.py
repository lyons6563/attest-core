#!/usr/bin/env python3
"""
Run integrity verification heartbeat and send email notification.

Usage:
    python scripts/run_integrity_check.py

Requires environment variables:
    SMTP_HOST
    SMTP_PORT (default: 587)
    SMTP_USERNAME
    SMTP_PASSWORD
    HEARTBEAT_TO
    HEARTBEAT_FROM
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.integrity_verifier import verify_integrity, send_heartbeat_email


def main():
    print("Running integrity verification...")
    result = verify_integrity()

    # Print result to console
    print(f"\nVerified at: {result['verified_at']}")
    print(f"Chains checked: {result['chains_checked']}")
    print(f"Status: {result['status']}")

    if result.get("details"):
        print("\nMismatches found:")
        for mismatch in result["details"]:
            print(f"  Chain: {mismatch['chain_id']}")
            print(f"  Event ID: {mismatch['event_id']}")
            print(f"  Reason: {mismatch['reason']}")
            if "computed" in mismatch:
                print(f"  Computed: {mismatch['computed'][:32]}...")
                print(f"  Stored: {mismatch['stored'][:32] if mismatch.get('stored') else 'NULL'}...")
            elif "computed_head" in mismatch:
                print(f"  Computed head: {mismatch['computed_head'][:32]}...")
                print(f"  Stored head: {mismatch['stored_head'][:32] if mismatch.get('stored_head') else 'NULL'}...")
            elif "expected" in mismatch:
                print(f"  Expected: {mismatch['expected'][:32] if mismatch.get('expected') else 'NULL'}...")
                print(f"  Stored: {mismatch['stored'][:32] if mismatch.get('stored') else 'NULL'}...")
            print()

    # Send heartbeat email
    try:
        print("Sending heartbeat email...")
        send_heartbeat_email(result)
        print("Email sent successfully.")
    except Exception as e:
        print(f"ERROR: Failed to send email: {e}", file=sys.stderr)
        sys.exit(1)

    # Exit with error code if verification failed
    if result["status"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
