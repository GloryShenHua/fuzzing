# Task 3 工作说明：DensityPowerSchedule 调度策略实现

周乐宇

## 一、工作目标

在 Fuzzing 实验框架中完成 **任务 3：增加至少一种新的调度策略，并放置于 `schedule` 包中**。

本任务实现了一个新的调度策略 `DensityPowerSchedule`。它的目标是在已有 `PathPowerSchedule` 之外，提供另一种 seed 选择思路：不仅关注 seed 覆盖了多少代码，还关注这些覆盖是否稀有、路径是否被反复触发、以及输入本身是否足够短。

最终实现位于：

```text
simple_fuzzer/schedule/density_power_schedule.py
```

并通过 `main.py` 中的 `--schedule` 参数切换：

```bash
uv run main.py --sample 1 --run-time 60 --schedule density
```

## 二、原始思路与改进动机

最初的 `DensityPowerSchedule` 采用较简单的覆盖密度公式：

```text
Energy = Coverage_Size / (Seed_Length + 1)
```

它表达的含义是：如果一个 seed 覆盖了更多代码，并且输入长度较短，那么它的“覆盖性价比”更高，应该获得更多被选中的机会。

这个想法本身是合理的，但在后续测试中发现两个问题：

1. **接口不完整**：项目入口中即使选择 `--schedule density`，仍然使用 `PathGreyBoxFuzzer`。而 `PathGreyBoxFuzzer` 会调用 `schedule.update_path_frequency()` 并读取 `schedule.path_frequency`。原始 `DensityPowerSchedule` 没有这两个接口，因此会触发 `AttributeError`。
2. **策略粒度偏粗**：仅用 `len(seed.coverage)` 衡量覆盖价值，会把常见覆盖行和稀有覆盖行等价处理。如果某些行已经被大量输入反复覆盖，继续围绕这些 seed 变异的边际收益较低。

因此，当前版本将 `DensityPowerSchedule` 从“普通覆盖密度”改进为“稀有覆盖密度”策略。

## 三、当前策略设计

当前 `DensityPowerSchedule` 维护两个频率表：

```python
self.path_frequency: Dict[Tuple[Location, ...], int] = {}
self.line_frequency: Dict[Location, int] = {}
```

其中：

- `path_frequency` 记录每条路径被触发的次数。
- `line_frequency` 记录每个覆盖行被触发的次数。

路径标识仍然使用排序后的覆盖集合：

```python
def path_id(self, coverage: Set[Location]) -> Tuple[Location, ...]:
    return tuple(sorted(coverage))
```

这样可以保证同一组覆盖行总是生成相同的路径 key，不受 Python `set` 遍历顺序影响。

每次执行结束后，`PathGreyBoxFuzzer` 会调用：

```python
def update_path_frequency(self, coverage: Set[Location]) -> bool:
    path = self.path_id(coverage)
    is_new_path = path not in self.path_frequency
    self.path_frequency[path] = self.path_frequency.get(path, 0) + 1

    for location in coverage:
        self.line_frequency[location] = self.line_frequency.get(location, 0) + 1

    return is_new_path
```

该函数一方面保证 `density` 调度器与 `PathGreyBoxFuzzer` 的接口兼容，另一方面也收集后续能量分配所需的覆盖频率信息。

## 四、Energy 分配公式

当前 energy 分配逻辑如下：

```python
rare_line_score = sum(
    1.0 / self.line_frequency.get(location, 1)
    for location in seed.coverage
)
input_size = max(1, len(seed.data))
path_frequency = self.path_frequency.get(self.path_id(seed.coverage), 1)
path_rarity = 1.0 / path_frequency

seed.energy = max((rare_line_score * path_rarity) / input_size, 1e-9)
```

可以概括为：

```text
Energy = Rare_Line_Score * Path_Rarity / Input_Size
```

其中：

```text
Rare_Line_Score = sum(1 / line_frequency[line] for line in seed.coverage)
Path_Rarity     = 1 / path_frequency[path]
Input_Size      = max(1, len(seed.data))
```

该公式包含三层含义：

1. **优先覆盖稀有行**：如果某些代码行很少被触发，那么覆盖这些行的 seed 更有继续探索价值。
2. **优先低频路径**：如果某条路径很少出现，说明它代表较少探索过的程序状态，应给予更高能量。
3. **优先短输入**：短输入执行和变异成本更低，也更适合作为后续 mutation 的基础。

`max(..., 1e-9)` 用于保证 energy 始终为正数，避免父类 `PowerSchedule.normalized_energy()` 中出现能量总和为 0 的情况。

## 五、与 PathPowerSchedule 的区别

`PathPowerSchedule` 的核心依据是路径频率：

```text
Energy = 1 / path_frequency^2
```

它主要回答的是：“哪条路径较少被探索？”

`DensityPowerSchedule` 则同时考虑路径、覆盖行和输入长度：

```text
Energy = Rare_Line_Score * Path_Rarity / Input_Size
```

它回答的是：“哪个 seed 用更短输入触发了更稀有的覆盖？”

因此两者关注点不同：

| Scheduler | 主要依据 | 优势 |
|---|---|---|
| PathPowerSchedule | 路径频率 | 简洁直接，鼓励低频路径 |
| DensityPowerSchedule | 稀有覆盖行、路径频率、输入长度 | 更细粒度地衡量 seed 覆盖价值 |

## 六、与 GreyBoxFuzzer 修改的关系

为了让 `DensityPowerSchedule` 更稳定地发挥作用，`GreyBoxFuzzer` 的 seed 入池策略也做了配套调整。

原始逻辑中，只有带来新覆盖且执行结果为 `PASS` 的输入会进入 `population`。当前逻辑调整为：只要输入带来新覆盖，即使触发 crash，也加入 `population` 作为后续变异的 frontier seed。

这样做的原因是：在模糊测试中，crash 输入不一定没有继续探索价值。某些输入虽然触发异常，但它已经到达了更深层的控制流位置。继续围绕它变异，可能更容易触发新的分支或更深路径。

该调整对 Sample 3 尤其明显。Sample 3 包含多层字符条件判断和异常分支，深层覆盖常常先通过异常输入暴露。如果丢弃这些 crash 输入，`density` 调度器可以选择的高价值 seed 会变少；保留这些 frontier seed 后，Sample 3 可以稳定达到完整覆盖。

## 七、代码修改清单

本任务相关修改包括：

1. **修改 `simple_fuzzer/schedule/density_power_schedule.py`**
   - 新增 `path_frequency`。
   - 新增 `line_frequency`。
   - 实现 `path_id()`。
   - 实现 `update_path_frequency()`。
   - 将能量公式从简单的 `coverage / length` 改为 `rare_line_score * path_rarity / input_size`。

2. **配合修改 `simple_fuzzer/fuzzer/grey_box_fuzzer.py`**
   - 新覆盖输入无论 `PASS` 还是 `FAIL`，都会加入 `population`。
   - crash 仍然独立记录到 `crash_map` 和 `crashes/`。
   - checkpoint 中保存 scheduler 状态，保证 `--resume` 后路径频率和行频率不会丢失。

3. **修改 `simple_fuzzer/main.py`**
   - 支持通过 `--schedule path` 与 `--schedule density` 切换调度策略。

## 八、测试方式

使用 `uv run` 执行项目入口。

基础检查：

```bash
uv run main.py --help
uv run python -m compileall .
```

对比测试命令：

```bash
uv run main.py --sample 1 --run-time 60 --quiet --schedule density
uv run main.py --sample 2 --run-time 60 --quiet --schedule density
uv run main.py --sample 3 --run-time 60 --quiet --schedule density
uv run main.py --sample 4 --run-time 60 --quiet --schedule density
```

完整测试矩阵还包含：

```text
path    × 60s  × Sample 1~4
path    × 300s × Sample 1~4
density × 60s  × Sample 1~4
density × 300s × Sample 1~4
```

## 九、测试结果

按目标 Sample 函数自身的可执行语句行统计覆盖率，最终结果如下：

| Scheduler | 运行时间 | Sample 1 | Sample 2 | Sample 3 | Sample 4 |
|---|---:|---:|---:|---:|---:|
| path | 60s | 8/8 (100.00%) | 13/13 (100.00%) | 9/9 (100.00%) | 2/2 (100.00%) |
| path | 300s | 8/8 (100.00%) | 13/13 (100.00%) | 9/9 (100.00%) | 2/2 (100.00%) |
| density | 60s | 8/8 (100.00%) | 13/13 (100.00%) | 9/9 (100.00%) | 2/2 (100.00%) |
| density | 300s | 8/8 (100.00%) | 13/13 (100.00%) | 9/9 (100.00%) | 2/2 (100.00%) |

唯一崩溃数量如下：

| Scheduler | 运行时间 | Sample 1 | Sample 2 | Sample 3 | Sample 4 |
|---|---:|---:|---:|---:|---:|
| path | 60s | 6 | 4 | 9 | 0 |
| path | 300s | 6 | 4 | 9 | 0 |
| density | 60s | 6 | 4 | 9 | 0 |
| density | 300s | 6 | 4 | 9 | 0 |

补充的 10 秒回归测试也显示当前策略稳定：

| Scheduler | Sample 1 | Sample 2 | Sample 3 | Sample 4 |
|---|---:|---:|---:|---:|
| path 10s | 100% / 6 crashes | 100% / 4 crashes | 100% / 9 crashes | 100% / 0 crashes |
| density 10s | 100% / 6 crashes | 100% / 4 crashes | 100% / 9 crashes | 100% / 0 crashes |

## 十、结果分析

测试结果说明，改进后的 `DensityPowerSchedule` 能够作为独立 Scheduler 正常运行，并在 4 个 Sample 上达到 100% 目标函数行覆盖率，满足任务中“增加至少一种新的调度策略”的要求。

与最初的简单覆盖密度公式相比，当前版本有三个改进：

1. **可运行性更强**：补齐了 `PathGreyBoxFuzzer` 所需接口，不再出现 `AttributeError`。
2. **调度信息更丰富**：不仅看覆盖行数量，还看覆盖行和路径是否稀有。
3. **探索能力更稳定**：配合 GreyBoxFuzzer 的 frontier seed 入池策略，可以稳定覆盖 Sample 3 的深层分支。

从 60 秒和 300 秒对比看，300 秒显著增加执行次数，但覆盖率和唯一崩溃数量基本不再增长。这说明当前 4 个 Sample 的主要分支和崩溃类型在 60 秒内已经基本被发现，300 秒测试更多体现长时间运行稳定性。

## 十一、结论

`DensityPowerSchedule` 已完成并通过测试。当前实现不再只是简单的一行 `coverage / length`，而是一个同时考虑稀有覆盖行、路径频率和输入长度的调度策略。

最终结果表明：

1. `density` 调度策略可以正常接入现有 fuzzing 框架。
2. `density` 在 4 个 Sample 上均达到 100% 目标函数行覆盖率。
3. `density` 与 `path` 均满足 50%+ 覆盖率要求。
4. 配合新的 seed 入池策略后，深层分支探索更加稳定。

因此，Task 3 的新增调度策略实现完整、可运行，并具备清晰的实验依据。
