"""`uv run spend` - show account balance, key limit and this project's spend. Prints numbers only."""
import httpx

from .llm import LEDGER, Ledger, Limits, fetch_status, load_key


def main() -> None:
    s = fetch_status(httpx.Client(), load_key())
    L, spent = Limits(), Ledger().total()
    print(f"Account credit left   ${s['account_remaining']:.2f}   (stop below ${L.account_floor:.2f})")
    if s["key_remaining"] is not None:
        print(f"Key limit left        ${s['key_remaining']:.2f}   (stop below ${L.key_floor:.2f})")
    print(f"Key usage this month  ${s['key_usage_monthly']:.2f}   (all tools on this key)")
    print(f"This project, total   ${spent:.4f}  of ${L.project_cap:.2f} cap   ledger: {LEDGER}")


if __name__ == "__main__":
    main()
