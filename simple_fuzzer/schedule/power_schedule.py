import random
from typing import List, Sequence

from utils.seed import Seed

MAX_SEEDS = 1000


class PowerSchedule:

    def assign_energy(self, population: Sequence[Seed]) -> None:
        """Assigns each seed the same energy"""
        for seed in population:
            seed.energy = 1

    def normalized_energy(self, population: List[Seed]) -> List[float]:
        """Normalize energy"""
        energy = list(map(lambda seed: seed.energy, population))
        sum_energy = sum(energy)  # Add up all values in energy
        assert sum_energy != 0
        norm_energy = list(map(lambda nrg: nrg / sum_energy, energy))
        return norm_energy

    def choose(self, population: List[Seed]) -> Seed:
        """Choose weighted by normalized energy.
           人口裁剪由  GreyBoxFuzzer  在持久化淘汰  seed  后统一完成，
           此处不再直接删除元素。
        """
        self.assign_energy(population)
        norm_energy = self.normalized_energy(population)
        seed: Seed = random.choices(population, weights=norm_energy)[0]
        return seed
