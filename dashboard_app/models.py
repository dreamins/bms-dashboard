from dataclasses import dataclass, field
from typing import List

@dataclass
class BatteryData:
    voltage: float = 0.0
    current: float = 0.0
    power_w: float = 0.0
    cell_voltages: List[float] = field(default_factory=lambda: [0.0] * 16)
    temp_env: int = 0
    temp_mos: int = 0
    soc: int = 0
    soh: int = 0
    cycles: int = 0
    status: int = 0
    raw_hex: str = ""
