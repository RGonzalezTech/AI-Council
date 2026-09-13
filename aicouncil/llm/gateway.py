"""
LLM gateway — the single seam between the council and any model provider.

`LLMGateway` is the protocol the rest of the package depends on. The default
implementation wraps LiteLLM + Instructor. Tests plug in `FakeGateway`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..settings import Settings

logger = logging.getLogger("aicouncil")

T = TypeVar("T", bound=BaseModel)


class LLMGateway(Protocol):
    """Structured completion: (model, system, user, schema) → validated schema instance."""

    def complete(
        self,
        *,
        model: str,
        response_model: type[T],
        system: str,
        user: str,
    ) -> T: ...


class InstructorGateway:
    """LiteLLM + Instructor implementation of `LLMGateway`."""

    def __init__(self, settings: Settings) -> None:
        import instructor
        import litellm
        from litellm import completion

        litellm.suppress_debug_info = True
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.ERROR)
        # Instructor logs every failed attempt at ERROR; we surface the final
        # exception ourselves, so suppress the duplicates.
        logging.getLogger("instructor").setLevel(logging.CRITICAL)

        self._settings = settings
        self._tools_client = instructor.from_litellm(completion)
        self._json_client = instructor.from_litellm(completion, mode=instructor.Mode.JSON)

    def _client_for(self, model: str):
        provider = model.split("/", 1)[0].lower()
        if provider in self._settings.json_mode_providers:
            return self._json_client
        return self._tools_client

    def complete(
        self,
        *,
        model: str,
        response_model: type[T],
        system: str,
        user: str,
    ) -> T:
        logger.debug("LLM → model=%s schema=%s", model, response_model.__name__)
        result = self._client_for(model).chat.completions.create(
            model=model,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_retries=self._settings.max_retries,
        )
        logger.debug("LLM ← %s", response_model.__name__)
        return result


Responder = Callable[[str, str, str], BaseModel]
"""(model, system, user) -> schema instance"""


class FakeGateway:
    """
    Deterministic gateway for tests.

    Register a responder per schema type. Each call is recorded in `calls`.
    """

    def __init__(self) -> None:
        self._responders: dict[type[BaseModel], Responder] = {}
        self.calls: list[dict[str, str]] = []

    def on(self, schema: type[T], responder: Responder | T) -> FakeGateway:
        if isinstance(responder, BaseModel):
            fixed = responder
            self._responders[schema] = lambda *_: fixed
        else:
            self._responders[schema] = responder
        return self

    def complete(
        self,
        *,
        model: str,
        response_model: type[T],
        system: str,
        user: str,
    ) -> T:
        self.calls.append(
            {"model": model, "schema": response_model.__name__, "system": system, "user": user}
        )
        try:
            responder = self._responders[response_model]
        except KeyError:
            raise AssertionError(
                f"FakeGateway has no responder for {response_model.__name__}"
            ) from None
        result = responder(model, system, user)
        if not isinstance(result, response_model):
            raise AssertionError(
                f"Responder for {response_model.__name__} returned {type(result).__name__}"
            )
        return result
