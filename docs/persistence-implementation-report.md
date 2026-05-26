# 持久化功能实现报告

## 一、实现目标

使用 `object_utils` 将 seed 及相关中间结果持久化到文件系统，解决长时间运行时内存持续增长的问题。

## 二、修改的文件

共修改 **6 个文件**，新增约 **80 行**有效代码：

| 文件 | 改动概述 |
|------|----------|
| `fuzzer/grey_box_fuzzer.py` | 核心持久化逻辑：seed 淘汰落盘、崩溃落盘、覆盖率周期快照、断点保存/恢复 |
| `runner/function_coverage_runner.py` | 新增 `trim_coverage_history()`，定期修剪无上限的覆盖率历史列表 |
| `schedule/power_schedule.py` | 从 `choose()` 中移除无持久化的静默删除逻辑，将 population 裁剪职责移交给 Fuzzer |
| `schedule/path_power_schedule.py` | 修复 `assign_energy` 空实现导致的 `AssertionError` bug |
| `main.py` | 新增 `--persist-dir` 和 `--resume` 命令行参数 |
| `.gitignore` | 排除 `_result/` 和 `_persist/` 输出目录 |

## 三、详细实现内容

### 3.1 Seed 淘汰持久化

- **位置**：`grey_box_fuzzer.py` 的 `_evict_lowest_seed()` 方法
- **机制**：当 population 超过 `MAX_POPULATION`（1000）时，找到能量最低的 seed，先用 `dump_object` 将其序列化保存到 `_persist/evicted_seeds/seed_XXXXXX.pkl`，再从内存中删除
- **效果**：内存中永远不超过 1000 个 seed 对象；被淘汰的 seed 不丢失，可用于离线分析

### 3.2 崩溃持久化

- **位置**：`grey_box_fuzzer.py` 的 `_persist_crash()` 方法
- **机制**：检测到 `Runner.FAIL` 时，仅在 crash_hash 未重复时才写入磁盘（与 `crash_map` 的去重逻辑一致），保存 input 字符串、MD5 stack hash、时间戳
- **位置**：`_persist/crashes/crash_XXXXXX.pkl`
- **效果**：每个唯一崩溃类型只存一份，避免磁盘膨胀

### 3.3 覆盖率周期快照

- **位置**：`grey_box_fuzzer.py` 的 `_persist_coverage_snapshot()` 方法
- **机制**：每 `SNAPSHOT_INTERVAL`（30 秒）自动保存当前覆盖率摘要（时间戳、已覆盖行数、总执行次数、唯一崩溃数）
- **位置**：`_persist/coverage_snapshots/snapshot_XXXX.pkl`
- **效果**：提供可回溯的覆盖率增长曲线，方便绘制实验图表

### 3.4 Runner 内存修剪

- **位置**：`function_coverage_runner.py` 的 `trim_coverage_history()` 方法
- **机制**：`cumulative_coverage` 列表每次执行都会 append，长时间运行可达数十万条。周期修剪仅保留最近 1000 条记录
- **调用时机**：与覆盖率快照同步，每 30 秒触发一次
- **效果**：`cumulative_coverage` 内存占用从 O(n) 降为 O(1)

### 3.5 断点保存与恢复

- **位置**：`grey_box_fuzzer.py` 的 `save_checkpoint()` / `load_checkpoint()` 方法
- **机制**：
  - 运行结束时自动保存 checkpoint（population、covered_line、crash_map、total_execs、seed_index）
  - 启动时通过 `--resume` 参数恢复，跳过种子阶段，直接从上次状态继续 fuzzing
- **位置**：`_persist/checkpoint.pkl`
- **效果**：支持中断后继续，避免长时间实验因意外中断而丢失进度

### 3.6 附带修复

- `PowerSchedule.choose()` 原先在 population 超 1000 时直接删除最低能量 seed（无持久化），现已将删除逻辑移至 `GreyBoxFuzzer._evict_lowest_seed()`，确保先落盘再删除
- `PathPowerSchedule.assign_energy()` 原先为空实现（只有 `# TODO`），导致所有 seed 能量为 0，触发 `normalized_energy` 的 `assert sum_energy != 0` 崩溃。现已回退到父类的均匀能量分配作为临时方案

## 四、文件系统布局

```
simple_fuzzer/
└── _persist/                          # 持久化根目录（可通过 --persist-dir 自定义）
    ├── evicted_seeds/                 # 被淘汰的种子
    │   └── seed_XXXXXX.pkl            #   序列化的 Seed 对象
    ├── crashes/                       # 崩溃记录
    │   └── crash_XXXXXX.pkl           #   {input, stack_hash, timestamp}
    ├── coverage_snapshots/            # 覆盖率快照（每 30 秒）
    │   └── snapshot_XXXX.pkl          #   {timestamp, covered_line_count, total_execs, unique_crashes}
    └── checkpoint.pkl                 # 断点恢复文件
```

## 五、成果验证

### 5.1 基本运行验证

```bash
cd simple_fuzzer
uv run main.py --sample 1 --run-time 60 --quiet
```

运行结束后检查目录结构：

```bash
ls _persist/
# 预期输出：checkpoint.pkl  crashes/  coverage_snapshots/  evicted_seeds/
```

### 5.2 崩溃去重验证

```bash
# 查看崩溃文件数量
ls _persist/crashes/ | wc -l

# 查看程序输出的 Crashes Num
# 两者数量应一致
```

### 5.3 覆盖率快照验证

```bash
# 运行超过 30 秒后，应存在快照文件
ls _persist/coverage_snapshots/

# 反序列化查看快照内容
python -c "from utils.object_utils import load_object; \
           snap = load_object('_persist/coverage_snapshots/snapshot_0000.pkl'); \
           print(snap)"
# 预期输出：{'timestamp': ..., 'covered_line_count': ..., 'total_execs': ..., 'unique_crashes': ...}
```

### 5.4 Seed 淘汰验证（需较大 population）

```bash
# 运行较长时间（如 600 秒），使 population 有机会达到 1000 上限
uv run main.py --sample 4 --run-time 600 --quiet

# 检查淘汰的 seed
ls _persist/evicted_seeds/ | wc -l

# 验证淘汰的 seed 可反序列化
python -c "from utils.object_utils import load_object; \
           seed = load_object('_persist/evicted_seeds/seed_000000.pkl'); \
           print(f'data: {seed.data[:50]}..., energy: {seed.energy}')"
```

### 5.5 断点恢复验证

```bash
# 第一次运行（短时间）
uv run main.py --sample 1 --run-time 10 --quiet

# 第二次运行，带上 --resume
uv run main.py --sample 1 --run-time 5 --resume --quiet

# 预期输出：[*] Resumed from checkpoint: XXXXX execs, XX covered lines, X unique crashes
# 然后从上次的状态继续 fuzzing
```

### 5.6 自定义持久化目录验证

```bash
uv run main.py --sample 1 --run-time 10 --quiet --persist-dir _my_persist
ls _my_persist/
# 预期：目录结构与 _persist/ 相同
```

## 六、内存改善分析

| 数据结构 | 修改前 | 修改后 |
|----------|--------|--------|
| `population` | 不超过 1000（但淘汰时数据丢失） | 不超过 1000（淘汰前持久化到磁盘） |
| `cumulative_coverage` | 每次执行 +1，300 秒约 3~30 万元素 | 每 30 秒修剪一次，不超过 1000 元素 |
| `crash_map` | 无上限（但崩溃总数有限） | 无变化（崩溃总数本身有限） |
| `covered_line` | 有限（取决于被测程序行数） | 无变化（本身有限） |