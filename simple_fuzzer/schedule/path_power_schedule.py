from typing import Dict, Sequence

from schedule.power_schedule import PowerSchedule
from utils.seed import Seed


class PathPowerSchedule(PowerSchedule):

    def __init__(self) -> None:
        super().__init__()
        # TODO

    def assign_energy(self, population: Sequence[Seed]) -> None:
        """Assign exponential energy inversely proportional to path frequency"""
        # TODO: 实现基于路径频率的能量分配
        # 当前回退到父类的均匀分配，保证 fuzzer 能够运行
        super().assign_energy(population)
