#!/usr/bin/env python3
"""Generate RSA key pair for the license service (run once)."""

from config import LICENSE_DATA_DIR, PRIVATE_KEY_PATH, PUBLIC_KEY_PATH
from tokens import generate_key_pair


def main() -> None:
    LICENSE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PRIVATE_KEY_PATH.exists():
        print(f"Keys already exist:\n  {PRIVATE_KEY_PATH}\n  {PUBLIC_KEY_PATH}")
        return
    generate_key_pair(PRIVATE_KEY_PATH, PUBLIC_KEY_PATH)
    print("[OK] Generated license signing keys:")
    print(f"  Private (keep on license server only): {PRIVATE_KEY_PATH}")
    print(f"  Public (deploy to PrimeNet clients):     {PUBLIC_KEY_PATH}")


if __name__ == "__main__":
    main()
