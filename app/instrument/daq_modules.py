"""34970A/34972A 插槽模块与通道范围。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlotInfo:
    slot: int
    model: str
    channels: tuple[int, ...] = ()
    current_channels: tuple[int, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.channels

    @property
    def label(self) -> str:
        return self.model or "Empty"

    @property
    def channel_text(self) -> str:
        if not self.channels:
            return "—"
        return f"{self.channels[0]}–{self.channels[-1]}"


def parse_slot(slot: int, raw: str) -> SlotInfo:
    parts = [part.strip() for part in raw.split(",")]
    model = parts[1] if len(parts) > 1 else ""
    model = model.upper()
    if model in {"", "0", "NONE"}:
        return SlotInfo(slot=slot, model="Empty")
    base = slot + 1
    if model == "34901A":
        mux = tuple(range(base, base + 20))
        current = (base + 20, base + 21)
        return SlotInfo(slot, model, mux + current, current)
    if model == "34902A":
        return SlotInfo(slot, model, tuple(range(base, base + 16)))
    if model == "34903A":
        return SlotInfo(slot, model, tuple(range(base, base + 20)))
    if model == "34904A":
        return SlotInfo(slot, model, tuple(range(base, base + 32)))
    if model == "34908A":
        return SlotInfo(slot, model, tuple(range(base, base + 40)))
    return SlotInfo(slot, model)


def default_slots() -> list[SlotInfo]:
    # 未读取槽位前按只有 1 号槽 34901A 处理，保持旧配置可用。
    base = 101
    mux = tuple(range(base, base + 20))
    current = (121, 122)
    return [SlotInfo(100, "34901A", mux + current, current)]
