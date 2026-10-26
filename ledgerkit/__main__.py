"""Allow `python -m ledgerkit ...` as documented in the README."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
