from typing import Dict, Sequence, Set, Tuple

from schedule.power_schedule import PowerSchedule
from utils.coverage import Location
from utils.seed import Seed


class DensityPowerSchedule(PowerSchedule):
    """
    Assign energy by rare coverage density.

    Shorter seeds that exercise more, and rarer, code locations receive more
    energy.  The path-frequency hooks keep this scheduler compatible with
    PathGreyBoxFuzzer's progress reporting.
    """

    def __init__(self) -> None:
        super().__init__()
        self.path_frequency: Dict[Tuple[Location, ...], int] = {}
        self.line_frequency: Dict[Location, int] = {}

    def path_id(self, coverage: Set[Location]) -> Tuple[Location, ...]:
        """Return a stable identifier for an execution path."""
        return tuple(sorted(coverage))

    def update_path_frequency(self, coverage: Set[Location]) -> bool:
        """Record one execution and return whether it found a new path."""
        path = self.path_id(coverage)
        is_new_path = path not in self.path_frequency
        self.path_frequency[path] = self.path_frequency.get(path, 0) + 1

        for location in coverage:
            self.line_frequency[location] = self.line_frequency.get(location, 0) + 1

        return is_new_path

    def assign_energy(self, population: Sequence[Seed]) -> None:
        """Assign energy based on rare covered lines per input byte."""
        for seed in population:
            if not seed.coverage:
                seed.energy = 1e-9
                continue

            rare_line_score = sum(
                1.0 / self.line_frequency.get(location, 1)
                for location in seed.coverage
            )
            input_size = max(1, len(seed.data))
            path_frequency = self.path_frequency.get(self.path_id(seed.coverage), 1)
            path_rarity = 1.0 / path_frequency

            seed.energy = max((rare_line_score * path_rarity) / input_size, 1e-9)
