"""Unified model router — one SDK for all backends."""

import base64
import io
import sys
import traceback
from pathlib import Path
from typing import AsyncIterator, Iterator, Literal
from openai import AsyncOpenAI, OpenAI
from PIL import Image

from core.config import config, ModelConfig

# ── Client factory ───────────────────────────────────

def _make_client(mc: ModelConfig) -> OpenAI:
    kwargs = {"api_key": mc.api_key, "base_url": mc.base_url, "timeout": 120.0}
    if not mc.api_key and mc.provider == "ollama":
        kwargs["api_key"] = "ollama"  # Ollama doesn't require real key
    return OpenAI(**kwargs)

def _make_async_client(mc: ModelConfig) -> AsyncOpenAI:
    kwargs = {"api_key": mc.api_key, "base_url": mc.base_url, "timeout": 120.0}
    if not mc.api_key and mc.provider == "ollama":
        kwargs["api_key"] = "ollama"
    return AsyncOpenAI(**kwargs)

_clients: dict[str, OpenAI] = {}
_async_clients: dict[str, AsyncOpenAI] = {}

def _get_client(name: str) -> OpenAI:
    if name not in _clients:
        mc = config.models.get(name)
        if not mc:
            raise ValueError(f"Unknown model: {name}")
        _clients[name] = _make_client(mc)
    return _clients[name]

def _get_async_client(name: str) -> AsyncOpenAI:
    if name not in _async_clients:
        mc = config.models.get(name)
        if not mc:
            raise ValueError(f"Unknown model: {name}")
        _async_clients[name] = _make_async_client(mc)
    return _async_clients[name]


# ── Image helpers ────────────────────────────────────

def _encode_image(image_path: str | Path) -> str:
    img = Image.open(image_path)
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > 2048:
        ratio = 2048 / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def _encode_image_data(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ── Chat messages types ──────────────────────────────

type TextContent = dict  # {"type": "text", "text": str}
type ImageContent = dict  # {"type": "image_url", "image_url": {"url": str}}
type Content = str | list[TextContent | ImageContent]

class Message:
    def __init__(self, role: Literal["system", "user", "assistant"], content: Content):
        self.role = role
        self.content = content


# ── Completion methods ───────────────────────────────

def chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> str | Iterator[str | dict]:
    """Synchronous chat completion. Returns string or stream iterator."""
    model_name = model or config.default_model
    mc = config.models.get(model_name)
    if not mc:
        raise ValueError(f"Unknown model: {model_name}")
    client = _get_client(model_name)

    kwargs = {
        "model": mc.model,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else mc.max_tokens,
        "temperature": temperature if temperature is not None else mc.temperature,
        "stream": stream,
    }

    # Enable DeepSeek thinking mode with budget (not reasoner, which has it built-in)
    if mc.provider == "deepseek" and "reasoner" not in mc.model:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    if stream:
        response = client.chat.completions.create(**kwargs)
        return _stream_iter(response)
    else:
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


async def achat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Async chat completion."""
    model_name = model or config.default_model
    mc = config.models.get(model_name)
    if not mc:
        raise ValueError(f"Unknown model: {model_name}")
    client = _get_async_client(model_name)

    extra = {}
    if mc.provider == "deepseek" and "reasoner" not in mc.model:
        extra["extra_body"] = {"thinking": {"type": "enabled"}}

    resp = await client.chat.completions.create(
        model=mc.model,
        messages=messages,
        max_tokens=max_tokens if max_tokens is not None else mc.max_tokens,
        temperature=temperature if temperature is not None else mc.temperature,
        **extra,
    )
    return resp.choices[0].message.content or ""


def vision(
    prompt: str,
    image_paths: list[str | Path],
    model: str = "qwen-vl",
    max_tokens: int | None = None,
) -> str:
    """Analyze images with a vision model."""
    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        b64 = _encode_image(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    return chat(
        messages=[{"role": "user", "content": content}],
        model=model,
        max_tokens=max_tokens if max_tokens is not None else 1024,
        temperature=0.0,
    )


def _stream_iter(response) -> Iterator[str | dict]:
    finish = None
    has_reasoning = False
    try:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                if chunk.choices[0].finish_reason:
                    finish = chunk.choices[0].finish_reason
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                has_reasoning = True
                yield {"_reasoning": reasoning}
            if delta.content:
                yield delta.content
            if chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
    except Exception:
        traceback.print_exc(file=sys.stderr)
        finish = None
    yield {"_finish_reason": finish or "unknown", "_has_reasoning": has_reasoning}


# ── Embedding ────────────────────────────────────────

def embed(text: str | list[str], model: str = "ollama") -> list[list[float]]:
    """Get embeddings via Ollama (local, free)."""
    client = _get_client(model)
    mc = config.models[model]

    texts = [text] if isinstance(text, str) else text
    resp = client.embeddings.create(
        model="bge-small",  # Ollama model name
        input=texts,
    )
    return [d.embedding for d in resp.data]
