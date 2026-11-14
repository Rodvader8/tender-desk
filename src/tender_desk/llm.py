"""OpenRouter client with hard spend limits.

The same OpenRouter account also runs other tools, so every call passes through
SpendGuard. It refuses to call the API when any of these is true:
  - this process has spent its per-run cap,
  - this project's ledger has reached the project cap,
  - the account balance would fall below the account floor,
  - the key's own remaining limit is below the key floor.
The API key is never logged, printed or written to the ledger.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .observability import observe_llm

BASE_URL = "https://openrouter.ai/api/v1"
KEY_FILE = Path.home() / ".config" / "openrouter" / "key"


def _ledger_path() -> Path:
    """TENDER_DESK_LEDGER if set (containers), else .spend/ in the project checkout, else the user's home."""
    if os.environ.get("TENDER_DESK_LEDGER"):
        return Path(os.environ["TENDER_DESK_LEDGER"])
    checkout = Path(__file__).resolve().parents[2]
    return (
        checkout / ".spend" / "ledger.jsonl"
        if (checkout / "pyproject.toml").exists()
        else Path.home() / ".tender-desk" / "ledger.jsonl"
    )


LEDGER = _ledger_path()
FALLBACK_USD_PER_TOKEN = 10e-6  # used only if the API omits cost; deliberately pessimistic

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass
class Limits:
    project_cap: float = field(default_factory=lambda: _f("TENDER_DESK_PROJECT_CAP_USD", 5.0))
    run_cap: float = field(default_factory=lambda: _f("TENDER_DESK_RUN_CAP_USD", 0.25))
    account_floor: float = field(default_factory=lambda: _f("TENDER_DESK_ACCOUNT_FLOOR_USD", 20.0))
    key_floor: float = field(default_factory=lambda: _f("TENDER_DESK_KEY_FLOOR_USD", 8.0))
    recheck_every: int = 20


def load_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not key:
        raise RuntimeError(f"No OpenRouter key: set OPENROUTER_API_KEY or create {KEY_FILE}")
    return key


def fetch_status(client: httpx.Client, key: str) -> dict:
    """Numbers only: account credit left, key limit left, key usage."""
    h = {"Authorization": f"Bearer {key}"}
    k = client.get(f"{BASE_URL}/key", headers=h, timeout=20).raise_for_status().json()["data"]
    c = client.get(f"{BASE_URL}/credits", headers=h, timeout=20).raise_for_status().json()["data"]
    return {
        "account_remaining": float(c["total_credits"]) - float(c["total_usage"]),
        "key_remaining": None if k.get("limit_remaining") is None else float(k["limit_remaining"]),
        "key_usage_monthly": float(k.get("usage_monthly") or 0),
        "key_usage_total": float(k.get("usage") or 0),
    }


class Ledger:
    def __init__(self, path: Path = LEDGER):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def total(self) -> float:
        if not self.path.exists():
            return 0.0
        return sum(json.loads(line)["cost"] for line in self.path.read_text().splitlines() if line.strip())

    def append(self, **rec) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"t": int(time.time()), **rec}) + "\n")


class SpendGuard:
    def __init__(self, ledger: Ledger, limits: Limits, status: Callable[[], dict]):
        self.ledger, self.limits, self._status = ledger, limits, status
        self.run_spent = 0.0
        self.calls = 0

    def check(self) -> None:
        L = self.limits
        if self.run_spent >= L.run_cap:
            raise BudgetExceeded(f"Run cap reached: ${self.run_spent:.4f} of ${L.run_cap:.2f}")
        total = self.ledger.total()
        if total >= L.project_cap:
            raise BudgetExceeded(f"Project cap reached: ${total:.4f} of ${L.project_cap:.2f}")
        if self.calls % L.recheck_every == 0:
            s = self._status()
            if s["account_remaining"] < L.account_floor:
                raise BudgetExceeded(f"Account balance ${s['account_remaining']:.2f} is below the ${L.account_floor:.2f} floor")
            if s["key_remaining"] is not None and s["key_remaining"] < L.key_floor:
                raise BudgetExceeded(f"Key limit left ${s['key_remaining']:.2f} is below the ${L.key_floor:.2f} floor")

    def record(self, model: str, cost: float, tokens: int, purpose: str) -> None:
        self.calls += 1
        self.run_spent += cost
        self.ledger.append(model=model, cost=cost, tokens=tokens, purpose=purpose)


class LLM:
    def __init__(
        self,
        model: str | None = None,
        limits: Limits | None = None,
        client: httpx.Client | None = None,
        ledger: Ledger | None = None,
        key: str | None = None,
    ):
        self.model = model or os.environ.get("TENDER_DESK_MODEL", "deepseek/deepseek-v4-flash")
        self._client = client or httpx.Client(timeout=120)
        self._key = key or load_key()
        self.guard = SpendGuard(ledger or Ledger(), limits or Limits(), lambda: fetch_status(self._client, self._key))

    def _post(self, body: dict, purpose: str) -> tuple[dict, float, int]:
        """One guarded call. Returns (choice, cost, tokens)."""
        self.guard.check()
        started = time.perf_counter()
        r = self._client.post(f"{BASE_URL}/chat/completions", json=body, headers={"Authorization": f"Bearer {self._key}"})
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        tokens = int(u.get("total_tokens", 0))
        cost = float(u["cost"]) if u.get("cost") is not None else tokens * FALLBACK_USD_PER_TOKEN
        self.guard.record(body["model"], cost, tokens, purpose)
        observe_llm(body["model"], purpose, time.perf_counter() - started, cost, tokens)
        return d["choices"][0], cost, tokens

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int = 1500,
        schema: dict | None = None,
        purpose: str = "chat",
    ) -> dict:
        body = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "usage": {"include": True},
            "temperature": 0,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}}
        choice, cost, tokens = self._post(body, purpose)
        return {
            "text": choice["message"]["content"] or "",
            "cost": cost,
            "tokens": tokens,
            "truncated": choice.get("finish_reason") == "length",
        }

    def complete_with_tools(
        self, messages: list[dict], tools: list[dict], *, max_tokens: int = 1500, purpose: str = "agent"
    ) -> dict:
        """One turn of a tool-calling conversation. Returns the assistant message (content and any tool_calls)."""
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "usage": {"include": True},
            "temperature": 0,
        }
        choice, cost, tokens = self._post(body, purpose)
        return {"message": choice["message"], "cost": cost, "tokens": tokens}

    def structured(
        self, messages: list[dict], model_cls: type[T], *, purpose: str = "structured", max_tokens: int = 3000, **kw
    ) -> T:
        schema = model_cls.model_json_schema()
        last_err: object = None
        for _ in range(2):
            out = self.chat(messages, schema=schema, purpose=purpose, max_tokens=max_tokens, **kw)
            if out["truncated"]:  # the answer ran out of room: retry once with double, never parse half a JSON
                last_err = "response cut off at max_tokens"
                max_tokens *= 2
                continue
            try:
                return model_cls.model_validate_json(out["text"])
            except ValidationError as e:
                last_err = e
                messages = messages + [
                    {"role": "user", "content": f"That did not match the schema: {e.errors()[:3]}. Reply with valid JSON only."}
                ]
        raise ValueError(f"Model output failed validation twice: {last_err}")
