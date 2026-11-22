"""UI → I/O 线程的命令对象。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import AcquisitionConfig, SerialSettings


@dataclass(frozen=True, slots=True)
class OpenCommand:
    settings: SerialSettings
    attempts: int = 5
    handshake_timeout_ms: int = 1500
    remote: bool = True


@dataclass(frozen=True, slots=True)
class CloseCommand:
    pass


@dataclass(frozen=True, slots=True)
class IdentifyCommand:
    pass


@dataclass(frozen=True, slots=True)
class SingleReadCommand:
    pass


@dataclass(frozen=True, slots=True)
class ListResourcesCommand:
    pass


@dataclass(frozen=True, slots=True)
class ScpiCommand:
    text: str


@dataclass(frozen=True, slots=True)
class SetDisplayCommand:
    on: bool


@dataclass(frozen=True, slots=True)
class SetBeeperCommand:
    on: bool


@dataclass(frozen=True, slots=True)
class ConfigureAcquisitionCommand:
    config: AcquisitionConfig


@dataclass(frozen=True, slots=True)
class StartAcquisitionCommand:
    config: AcquisitionConfig


@dataclass(frozen=True, slots=True)
class StopAcquisitionCommand:
    pass


@dataclass(frozen=True, slots=True)
class ShutdownCommand:
    pass
