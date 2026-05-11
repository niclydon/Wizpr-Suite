from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def _client() -> Any | None:
    if os.environ.get("LANGFUSE_ENABLED") != "true":
        return None
    if not os.environ.get("LANGFUSE_PUBLIC_KEY") or not os.environ.get("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import Langfuse  # type: ignore
        kwargs = {"public_key": os.environ["LANGFUSE_PUBLIC_KEY"], "secret_key": os.environ["LANGFUSE_SECRET_KEY"]}
        if os.environ.get("LANGFUSE_BASE_URL"):
            kwargs["host"] = os.environ["LANGFUSE_BASE_URL"]
        return Langfuse(**kwargs)
    except Exception:
        return None


async def observed_generation(name: str, model: str, prompt: str, fn: Callable[[], Awaitable[T]]) -> T:
    lf = _client()
    trace = None
    generation = None
    try:
        if lf is not None:
            trace = lf.trace(name=name, input={"prompt_chars": len(prompt)}, metadata={"model": model})
            generation = trace.generation(name=name, model=model, input={"prompt_chars": len(prompt)})
    except Exception:
        trace = None
        generation = None
    try:
        result = await fn()
        output = {"type": result.__class__.__name__}
        generation.end(output=output) if generation is not None else None
        trace.update(output=output) if trace is not None else None
        lf.flush() if lf is not None else None
        return result
    except Exception as exc:
        try:
            generation.end(level="ERROR", status_message=str(exc)) if generation is not None else None
            lf.flush() if lf is not None else None
        except Exception:
            pass
        raise
