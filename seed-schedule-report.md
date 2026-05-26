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

