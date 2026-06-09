# Seed 调度部分实验报告

## 一、实验目标

本部分实验对应 PJ2 模糊测试任务中的 seed 调度实现，完成 `path_power_schedule.py` 与 `path_grey_box_fuzzer.py` 中基于路径频率的调度逻辑。实验目标是在已有灰盒 fuzzing 框架中引入覆盖率反馈，使 fuzzer 不再仅随机选择已有 seed，而是根据 seed 曾经触发的执行路径频率来分配变异机会。

在灰盒模糊测试中，seed 的价值通常与它能否触发新的控制流路径有关。如果某条路径已经被大量输入反复触发，继续围绕该路径变异的边际收益会下降；反之，低频路径更可能对应较少探索过的程序状态。因此，本实现将“路径出现频率”作为调度依据，让低频路径对应的 seed 获得更高能量，从而提高后续被选中并继续变异的概率。

## 二、相关模块

本部分实现主要涉及两个文件。

`simple_fuzzer/schedule/path_power_schedule.py` 负责维护路径频率表，并根据路径频率为 population 中的 seed 分配 energy。该文件继承基础调度器 `PowerSchedule`，最终仍复用父类中的加权随机选择逻辑。

`simple_fuzzer/fuzzer/path_grey_box_fuzzer.py` 负责在每次执行目标函数后读取 runner 采集到的覆盖率信息，并将本次执行路径反馈给 `PathPowerSchedule`。同时，它补充了路径相关统计信息，例如最近一次发现新路径的时间和当前已发现路径总数。

整体数据流如下：

1. `GreyBoxFuzzer` 生成输入并交给 `FunctionCoverageRunner` 执行。
2. `FunctionCoverageRunner` 使用 `Coverage` 记录本次执行覆盖到的函数和行号。
3. `PathGreyBoxFuzzer.run()` 在执行结束后读取 `runner.coverage()`。
4. `PathPowerSchedule.update_path_frequency()` 将覆盖率集合转换为路径标识，并更新频率。
5. 下一轮选择 seed 时，`PathPowerSchedule.assign_energy()` 根据路径频率设置 seed energy。
6. `PowerSchedule.choose()` 根据归一化后的 energy 进行加权随机选择。

## 三、路径频率记录方式

一次执行得到的覆盖率是一个集合，集合元素形如 `(function_name, line_number)`。由于 Python 的 `set` 不保证顺序，不能直接把原始集合当作稳定的路径标识。因此实现中先对覆盖率集合排序，再转换为 tuple：

```python
def path_id(self, coverage) -> Tuple[Location, ...]:
    return tuple(sorted(coverage))
```

这样做的原因是：只要两次执行覆盖到的函数行号集合一致，即使集合内部遍历顺序不同，排序后的 tuple 也相同。它可以稳定地作为字典 key，用于统计同一条路径被触发的次数。

路径频率表定义为：

```python
self.path_frequency: Dict[Tuple[Location, ...], int] = {}
```

每次执行结束后，调度器通过 `update_path_frequency()` 更新频率：

```python
def update_path_frequency(self, coverage) -> bool:
    path = self.path_id(coverage)
    is_new_path = path not in self.path_frequency
    self.path_frequency[path] = self.path_frequency.get(path, 0) + 1
    return is_new_path
```

该函数同时返回当前路径是否为新路径。`PathGreyBoxFuzzer` 利用这个返回值更新 `last_path_time`，用于输出统计信息。

## 四、Energy 分配策略

调度器的核心逻辑位于 `assign_energy()`：

```python
for seed in population:
    path = self.path_id(seed.coverage)
    frequency = self.path_frequency.get(path, 1)
    seed.energy = 1.0 / (frequency ** 2)
```

这里的设计思想是：路径频率越高，seed energy 越低；路径频率越低，seed energy 越高。`frequency` 使用默认值 `1`，表示如果某个 seed 的路径尚未出现在频率表中，它至少按首次出现路径处理，不会出现除零问题。

分母使用 `frequency ** 2`，是为了让高频路径受到更明显的能量衰减。如果使用 `1 / frequency`，频率为 1 和频率为 2 的路径能量分别为 1 和 0.5，差距相对温和；使用平方后，二者变为 1 和 0.25，低频路径优势更明显。这样可以减少 fuzzer 在常见路径上反复投入变异次数，引导它更多探索低频路径。

该策略并不会直接决定唯一的 seed，而是影响父类 `PowerSchedule.choose()` 中的加权随机选择。energy 会被归一化为权重，最终通过 `random.choices()` 从 population 中抽取 seed。因此调度结果仍保留随机性，但整体概率会偏向低频路径。

## 五、与 Fuzzer 主流程的结合

`PathGreyBoxFuzzer` 继承自 `GreyBoxFuzzer`，因此输入生成、新覆盖 seed 加入 population、崩溃统计等基础逻辑仍由父类完成。本部分只补充路径反馈逻辑：

```python
result, outcome = super().run(runner)

if self.schedule.update_path_frequency(runner.coverage()):
    self.last_path_time = time.time()

return result, outcome
```

执行顺序上，必须先调用 `super().run(runner)`，因为只有目标函数运行完成后，`FunctionCoverageRunner` 才会更新本次执行的覆盖率。随后 `PathGreyBoxFuzzer` 再读取 `runner.coverage()`，将本次覆盖路径反馈给调度器。

统计输出也增加了路径相关信息：

- `Last New Path`：最近一次发现新路径距离 fuzz 开始的时间。
- `Total Paths`：当前 `path_frequency` 中记录的不同路径数量。
- `Covered Lines`：截至当前累计覆盖到的代码行数量。

同时，`--quiet` 参数会控制是否打印统计表，避免在批量测试时输出过多中间信息。

## 六、运行与验证

本部分代码在 `feature/seed` 分支上验证。运行环境为 macOS，使用系统中的 `python3` 直接执行项目入口。项目入口位于 `simple_fuzzer/main.py`，运行时需要在 `simple_fuzzer` 目录下执行，因为语料库路径使用的是相对路径。

编译检查命令：

```bash
python3 -m py_compile main.py fuzzer/*.py runner/*.py samples/*.py schedule/*.py utils/*.py
```

功能验证命令：

```bash
for sample in 1 2 3 4; do
  python3 main.py --sample "$sample" --run-time 1 --output-dir _result --quiet
done
```

验证结果为 4 个样例均能正常完成运行，程序不再出现调度阶段的 `AssertionError`。运行结束后，结果会输出覆盖率集合、唯一崩溃集合、开始时间和结束时间，并写入 `_result/Sample-N.pkl`。

在实现前，`PathPowerSchedule.assign_energy()` 尚未为 seed 设置有效 energy，导致 population 中 seed 的 energy 总和为 0，父类 `PowerSchedule.normalized_energy()` 中的断言失败。实现路径频率调度后，每个 seed 都会根据其路径频率获得正数 energy，因此加权调度可以正常工作。

## 七、GreyBoxFuzzer 中 seed 管理与持久化完善

在后续测试过程中，进一步完善了 `GreyBoxFuzzer` 中 seed 管理和持久化逻辑。该部分虽然不直接属于 `PathPowerSchedule` 的 energy 公式，但它会直接影响 Scheduler 能够调度到哪些 seed，因此也是 seed 调度闭环中的关键环节。

### 7.1 新覆盖输入的入池策略

原始实现中，只有当输入带来新覆盖且执行结果为 `PASS` 时，才会被加入 `population`：

```python
if outcome == Runner.PASS:
    seed = Seed(self.inp, runner.coverage())
    self.population.append(seed)
```

这种策略在一般情况下可以工作，但对于 fuzzing 来说偏保守。某些输入虽然触发了异常，但它们已经进入了更深的分支，代表了有价值的程序状态。如果完全丢弃这些输入，后续 mutation 就无法继续围绕该深层路径附近进行探索。

因此当前实现调整为：只要输入带来新覆盖，就加入 `population` 作为后续变异的 frontier seed；如果该输入同时触发 crash，则仍然在 crash 逻辑中单独记录。

```python
if len(self.covered_line) != len(runner.all_coverage):
    self.covered_line |= runner.all_coverage
    seed = Seed(self.inp, runner.coverage())
    self.population.append(seed)
    if len(self.population) > self.MAX_POPULATION:
        self._evict_lowest_seed()

if outcome == Runner.FAIL:
    self.last_crash_time = time.time()
    if result not in self.crash_map.values():
        self._persist_crash(self.inp, result)
    self.crash_map[self.inp] = result
```

这样做的好处是，Scheduler 的候选集合不仅包含“正常通过”的输入，也包含“虽然崩溃但带来新覆盖”的输入。对于 Sample 3 这类深层条件分支，该策略可以显著提高继续探索深层分支的机会。

### 7.2 Population 上限与 seed 淘汰持久化

为了避免长时间 fuzzing 导致内存中的 `population` 无限增长，`GreyBoxFuzzer` 设置了 `MAX_POPULATION = 1000`。当 population 超出上限时，会淘汰当前 energy 最低的 seed。

淘汰前不会直接丢弃该 seed，而是将其序列化保存到磁盘：

```python
path = os.path.join(self.persist_dir, "evicted_seeds",
                    f"seed_{self._evict_counter:06d}.pkl")
dump_object(path, evicted)
self._evict_counter += 1
del self.population[min_idx]
```

这满足了“将 Seed 持久化进入文件系统、防止内存占用过高”的实验要求。内存中只保留当前最有调度价值的一部分 seed，被淘汰的 seed 仍保存在 `_persist*/evicted_seeds/` 中，便于后续分析或恢复。

### 7.3 Crash 与覆盖率快照持久化

除 seed 淘汰外，`GreyBoxFuzzer` 还会持久化 crash 信息和覆盖率快照：

```text
persist_dir/
├── checkpoint.pkl
├── crashes/
├── coverage_snapshots/
└── evicted_seeds/
```

其中：

- `crashes/` 保存唯一崩溃输入、栈哈希和时间戳。
- `coverage_snapshots/` 周期性保存覆盖行数、执行次数和唯一崩溃数。
- `checkpoint.pkl` 保存当前 population、覆盖集合、崩溃映射、执行次数和 seed 读取进度。

覆盖率快照默认每 30 秒写入一次：

```python
SNAPSHOT_INTERVAL = 30
```

长时间运行时，这可以记录 fuzzing 过程中的覆盖率增长趋势。

### 7.4 Checkpoint 与 resume 完善

为了支持 `--resume` 后继续 fuzzing，当前 checkpoint 除了保存基础状态外，还保存了 Scheduler 状态和持久化计数器：

```python
checkpoint = {
    "population": self.population,
    "covered_line": self.covered_line,
    "crash_map": self.crash_map,
    "total_execs": self.total_execs,
    "seed_index": self.seed_index,
    "schedule": self.schedule,
    "last_crash_time": self.last_crash_time,
    "persist_counters": {
        "evict": self._evict_counter,
        "snapshot": self._snapshot_counter,
        "crash": self._crash_counter,
    },
}
```

恢复时，`load_checkpoint()` 会恢复 population、覆盖率、crash map、执行次数和 Scheduler，并重新计算下一次应使用的文件编号：

```python
self._evict_counter = max(counters.get("evict", 0),
                          self._next_persist_index("evicted_seeds", "seed_"))
self._snapshot_counter = max(counters.get("snapshot", 0),
                             self._next_persist_index("coverage_snapshots", "snapshot_"))
self._crash_counter = max(counters.get("crash", 0),
                          self._next_persist_index("crashes", "crash_"))
```

这里额外扫描已有文件，是为了避免 resume 后从 `seed_000000.pkl`、`crash_000000.pkl` 或 `snapshot_0000.pkl` 重新写入，覆盖之前的结果。

## 八、补充验证结果

对持久化逻辑进行了最小化验证：

```text
crashes ['crash_000000.pkl', 'crash_000001.pkl']
snapshots ['snapshot_0000.pkl', 'snapshot_0001.pkl']
evicted ['seed_000000.pkl', 'seed_000001.pkl']
seed_000000.pkl Seed 'seed-a'
seed_000001.pkl Seed 'seed-c'
```

该结果说明：

1. crash 信息可以连续持久化，且 resume 后不会覆盖旧文件。
2. coverage snapshot 可以连续持久化，且编号正确递增。
3. 被淘汰的 Seed 对象可以保存到 `evicted_seeds/`，并能通过 `load_object()` 正确反序列化。

同时使用当前代码进行了 10 秒回归测试：

| Scheduler | Sample 1 | Sample 2 | Sample 3 | Sample 4 |
|---|---:|---:|---:|---:|
| path 10s | 100% / 6 crashes | 100% / 4 crashes | 100% / 9 crashes | 100% / 0 crashes |
| density 10s | 100% / 6 crashes | 100% / 4 crashes | 100% / 9 crashes | 100% / 0 crashes |

回归结果表明，新的 seed 入池策略和持久化恢复逻辑没有破坏原有 fuzzing 流程，且能够稳定达到目标 Sample 函数的高覆盖率。
