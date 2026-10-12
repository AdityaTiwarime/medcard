"""Server-side AI. The key lives in an environment variable and never reaches the browser.

A key typed by the user in the chat box wins for that request; otherwise
ANTHROPIC_API_KEY -> Claude, else OPENAI_API_KEY -> OpenAI, else AIUnavailable
(the frontend then shows its built-in offline answers).
"""
import base64
import os
import time
from collections import defaultdict, deque

DEFAULT_SYSTEM = ("You are MedCard AI, an intelligent medical assistant for the AI Integrated Medical "
                  "E-Card platform. Be helpful, concise, and health-literate. You do not diagnose; "
                  "always point people to their doctor for final decisions.")
MAX_CALLS_PER_HOUR = int(os.getenv("AI_CALLS_PER_HOUR", "40"))
_calls: dict[int, deque] = defaultdict(deque)


class AIUnavailable(Exception):
    pass


class RateLimited(Exception):
    pass


def provider() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


def _check_rate(user_id: int):
    now = time.time()
    q = _calls[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_CALLS_PER_HOUR:
        raise RateLimited()
    q.append(now)


def key_provider(api_key: str | None) -> str | None:
    """A user's own key (from the chat's API-key box): sk-ant-... is Claude, other sk-... is OpenAI."""
    if not api_key:
        return None
    return "anthropic" if api_key.startswith("sk-ant-") else "openai"


def complete(user_id: int, prompt: str, system: str | None = None,
             history: list[dict] | None = None, max_tokens: int = 1000,
             image: tuple[bytes, str] | None = None, api_key: str | None = None) -> str:
    """image = (bytes, mime) for a photographed report; it's attached to the final user message.
    api_key = the user's own key; it is used for this call only and never stored."""
    api_key = (api_key or "").strip() or None
    which = key_provider(api_key) or provider()
    if which == "offline":
        raise AIUnavailable()
    if not api_key:  # the hourly limit protects the server's key, not the user's own
        _check_rate(user_id)

    messages = [m for m in (history or []) if m.get("role") in ("user", "assistant") and m.get("content")]
    messages = messages[-12:]  # keep context small
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": prompt})
    system = system or DEFAULT_SYSTEM
    b64 = base64.b64encode(image[0]).decode() if image else None

    try:
        if which == "anthropic":
            import anthropic
            if image:
                messages[-1] = {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": image[1], "data": b64}},
                    {"type": "text", "text": messages[-1]["content"]}]}
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
            resp = client.messages.create(model=os.getenv("AI_MODEL", "claude-haiku-5-5"),
                                          max_tokens=max_tokens, system=system, messages=messages)
            return "".join(getattr(b, "text", "") for b in resp.content)

        from openai import OpenAI
        if image:
            messages[-1] = {"role": "user", "content": [
                {"type": "text", "text": messages[-1]["content"]},
                {"type": "image_url", "image_url": {"url": f"data:{image[1]};base64,{b64}"}}]}
        client = OpenAI(api_key=api_key) if api_key else OpenAI()
        resp = client.chat.completions.create(model=os.getenv("AI_MODEL", "gpt-4o-mini"),
                                              max_tokens=max_tokens,
                                              messages=[{"role": "system", "content": system}, *messages])
        return resp.choices[0].message.content or ""
    except Exception as exc:  # bad key, quota, network: let the UI fall back gracefully
        raise AIUnavailable(str(exc)) from exc
