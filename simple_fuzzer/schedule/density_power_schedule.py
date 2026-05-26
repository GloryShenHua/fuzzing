from typing import Sequence

from schedule.power_schedule import PowerSchedule
from utils.seed import Seed


class DensityPowerSchedule(PowerSchedule):
    """
    Assigns energy based on coverage density.
    Energy is proportional to the number of covered lines and inversely proportional to the seed length.
    This encourages the fuzzer to prefer smaller seeds that trigger a high amount of code execution.
    """

    def __init__(self) -> None:
        super().__init__()

    def assign_energy(self, population: Sequence[Seed]) -> None:
        """Assign energy based on coverage size and seed length"""
        for seed in population:
            # We use len(seed.coverage) as the numerator (more coverage = more energy)
            # and (len(seed.data) + 1) as the denominator (smaller size = more energy, +1 prevents division by zero).
            seed.energy = len(seed.coverage) / (len(seed.data) + 1)
