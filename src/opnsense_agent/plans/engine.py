"""Op handler protocol, registry, and (later) the apply pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from opnsense_agent.plans.schema import OpResult, PlanOp

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

logger = logging.getLogger(__name__)


class UnknownOpError(Exception):
    """Raised when no handler is registered for a given op type."""


@dataclass(frozen=True)
class HandlerContext:
    """Resources available to a handler during execution."""

    api: OpnApiClient
    ssh: OpnSshClient


@runtime_checkable
class OpHandler(Protocol):
    op_type: str

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult: ...


class OpHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, OpHandler] = {}

    def register(self, handler: OpHandler) -> None:
        if handler.op_type in self._handlers:
            raise ValueError(f"Op type {handler.op_type!r} already registered")
        self._handlers[handler.op_type] = handler
        logger.debug("Registered op handler: %s", handler.op_type)

    def get(self, op_type: str) -> OpHandler:
        try:
            return self._handlers[op_type]
        except KeyError as e:
            raise UnknownOpError(f"No handler for op type: {op_type!r}") from e

    def known_types(self) -> list[str]:
        return sorted(self._handlers.keys())
