from typing import Dict, Sequence, Tuple

from schedule.power_schedule import PowerSchedule
from utils.coverage import Location
from utils.seed import Seed


class PathPowerSchedule(PowerSchedule):

    def __init__(self) -> None:
        super().__init__()
        self.path_frequency: Dict[Tuple[Location, ...], int] = {}

    def path_id(self, coverage) -> Tuple[Location, ...]:
        """Return a stable identifier for an execution path."""
        return tuple(sorted(coverage))

    def update_path_frequency(self, coverage) -> bool:
        """Record one execution of a path and return whether it is new."""
        path = self.path_id(coverage)
        is_new_path = path not in self.path_frequency
        self.path_frequency[path] = self.path_frequency.get(path, 0) + 1
        return is_new_path

    def assign_energy(self, population: Sequence[Seed]) -> None:
        """Assign exponential energy inversely proportional to path frequency"""
        for seed in population:
            path = self.path_id(seed.coverage)
            frequency = self.path_frequency.get(path, 1)
            seed.energy = 1.0 / (frequency ** 2)
