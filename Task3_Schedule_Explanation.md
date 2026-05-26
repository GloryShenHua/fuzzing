# Task 3 工作说明：DensityPowerSchedule 调度策略实现
周乐宇
## 一、 工作目标
在 Fuzzing 实验框架中完成**任务 3：增加至少一种新的调度策略，并放入 `schedule` 包中**。
为了达到最佳的 Fuzzing 效率，我设计并实现了一种名为 **“覆盖率密度（Coverage Density）”** 的调度策略，并在 `main.py` 中实现了通过命令行参数快速切换验证的机制。

## 二、 策略设计原理 (DensityPowerSchedule)
在传统的灰盒模糊测试（如 AFL）中，调度器（Scheduler）负责给种子队列中的种子分配“能量”（即接下来的变异次数）。分配机制极其关键。

我实现的 `DensityPowerSchedule` 基于以下核心启发式规则：
1. **优先高覆盖**：触发程序执行了更多代码路径（即 `len(seed.coverage)` 更大）的种子，说明其包含了更能探索到程序深层状态的数据结构。
2. **优先短输入**：长度越短（`len(seed.data)` 越小）的种子，其变异越快，执行时间越短，并且变异后更不容易因为过长的无效字节被早期校验拦截。

**能量计算公式**：
$$ Energy = \frac{Coverage\_Size}{Seed\_Length + 1} $$
（分母加 1 是为了防止极端情况下空字符串导致的除以零错误）。

这促使 Fuzzer 像是在追求“代码覆盖的性价比”，能够极大地帮助工具发现触发相同路径但更短、更容易变异的优质种子。

## 三、 代码修改清单
本次工作全部基于独立的 `feature/schedule` 分支开发，修改不与其他同学的任务（变异器、持久化）产生冲突。

1. **新增 `simple_fuzzer/schedule/density_power_schedule.py`**
   - 继承了 `PowerSchedule` 基类。
   - 重写了 `assign_energy` 方法，实现了上述“覆盖率/长度”比值的能量分配算法。
2. **修改 `simple_fuzzer/main.py`**
   - 引入了 `argparse` 参数 `--schedule`。
   - 修改了 Fuzzer 的实例化逻辑：如果用户运行参数包含 `--schedule density`，则载入新编写的 `DensityPowerSchedule`，否则默认使用原有的 `PathPowerSchedule`。这极大地方便了后续编写实验报告时的效果对比。

## 四、 测试与运行方式
代码已通过本地运行测试。你可以通过以下命令对比新旧策略：

**1. 使用传统的 Path 调度策略（默认）：**
```bash
python simple_fuzzer/main.py --sample 4 --run-time 300
```

**2. 使用我新编写的 Density 调度策略：**
```bash
python simple_fuzzer/main.py --sample 4 --run-time 300 --schedule density
```

