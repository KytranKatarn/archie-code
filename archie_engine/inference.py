"""Ollama inference client for ARCHIE Engine."""

from __future__ import annotations

import aiohttp


class InferenceClient:
    """Async client for the Ollama REST API."""

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        timeout: int = 300,
    ) -> None:
        self.ollama_host = ollama_host.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def generate(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
    ) -> dict:
        """POST /api/generate — non-streaming text generation."""
        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate", json=payload
                ) as resp:
                    return await resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def chat(
        self,
        messages: list[dict],
        model: str,
        system: str | None = None,
    ) -> dict:
        """POST /api/chat — non-streaming chat completion."""
        payload: dict = {"model": model, "messages": messages, "stream": False}
        if system:
            payload["system"] = system
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/chat", json=payload
                ) as resp:
                    return await resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def list_models(self) -> list[dict]:
        """GET /api/tags — return list of available models."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    data = await resp.json()
                    return data.get("models", [])
        except Exception:
            return []

    async def is_available(self) -> bool:
        """Return True if Ollama is reachable (GET /api/tags returns 200)."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def warm_model(self, model: str) -> bool:
        """POST /api/generate with empty prompt to preload the model into memory."""
        payload = {"model": model, "prompt": "", "stream": False}
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate", json=payload
                ) as resp:
                    await resp.json()
                    return True
        except Exception:
            return False
