# 太阳敏上位机代码修改建议

> 审查日期：2026-06-01
> 审查范围：`太阳敏上位机/` 下所有 Python 源文件及单元测试
> 审查依据：[太阳敏上位机软件方案.md](太阳敏上位机软件方案.md)、[技术报告_太阳敏_无透镜版_0528.md](../技术报告_太阳敏_无透镜版_0528.md)、[校准与测试方案_10_4_GPT.md](../校准与测试方案_10_4_GPT.md)、电源模块上位机参考代码

---

## 总体评价

代码整体质量**远高于**电源模块参考代码。分层清晰、协议设计合理、单元测试覆盖了关键路径。11/12 个单元测试通过（唯一失败是 GUI 导入测试因缺少 pyqtgraph 依赖，不影响逻辑正确性）。

以下按严重程度分级列出所有问题，每条给出**复现方法、原因分析和修复代码**。

---

## 🔴 Bug（必须修复）

### Bug-1：`sun_simulator.py` 的 `drop_frame` 模式多丢一帧

**文件**：`sun_simulator.py` 第 28–32 行

**复现**：

```python
from sun_simulator import SunSimulator
from sun_protocol import TelemetryParser

sim = SunSimulator(node_id=1, rate_hz=10, mode="drop_frame", drop_frame_every=5)
parser = TelemetryParser()
seqs = []
for i in range(15):
    frame = sim.next_frame()
    for t in parser.feed(frame):
        seqs.append(t.seq)
print(seqs)
# 期望: [0,1,2,3,5,6,7,8,9,11,12,13,14,15,17]  每5帧丢1帧
# 实际: [0,1,2,3,6,7,8,9,10,13,14,15,16,17,20]  每5帧丢2帧
```

**原因**：代码先对 `_seq` 加 2（跳过1个序号），然后取 `seq = self._seq`，最后再对 `_seq` 加 1。总共前进 3，导致比前一帧跳了 2 个序号，丢帧数为 2 而非 1。

```python
# 当前代码（有 bug）
def next_telemetry(self) -> SunTelemetry:
    self._frame_index += 1
    if self.mode == "drop_frame" and self.drop_frame_every > 0 and self._frame_index % self.drop_frame_every == 0:
        self._seq = (self._seq + 2) & 0xFFFF      # ← 先跳2
    seq = self._seq                                 # ← 取值
    self._seq = (self._seq + 1) & 0xFFFF            # ← 再+1，总共前进3
```

**修复**：先正常取值和递增，再额外跳 1 个序号。

```python
def next_telemetry(self) -> SunTelemetry:
    self._frame_index += 1

    seq = self._seq
    self._seq = (self._seq + 1) & 0xFFFF
    if self.mode == "drop_frame" and self.drop_frame_every > 0 and self._frame_index % self.drop_frame_every == 0:
        self._seq = (self._seq + 1) & 0xFFFF       # ← 额外跳1，总共前进2，丢1帧

    self._timestamp_ms += int(round(1000.0 / max(self.rate_hz, 0.1)))
    # ... 后续不变
```

**验证**：修复后 `seqs` 应为 `[0,1,2,3,5,6,7,8,9,11,...]`，`parser.drop_count` 应等于丢帧触发次数。

---

### Bug-2：`sun_gui.py` 串口连接失败时按钮状态不一致

**文件**：`sun_gui.py` 第 194–219 行

**复现**：选择一个不存在的串口号，点击 Connect。按钮变为 "Disconnect" 但实际连接失败，弹窗关闭后按钮仍显示 "Disconnect"，用户需再次点击才能真正断开。

**原因**：`toggle_connection()` 在启动线程之前就将按钮文字改为 "Disconnect"。线程内的串口异常通过 `error_occurred` 信号发送到 `on_error`，但 `on_error` 只弹窗，没有回滚按钮状态。

**修复方案 A**（推荐）：在 `on_error` 中回滚按钮状态。

```python
def on_error(self, message: str) -> None:
    self.append_event(f"ERROR: {message}")
    self.statusBar().showMessage(f"ERROR: {message}")
    # 如果当前标记为已连接但出现错误，回滚按钮状态
    if self.host._thread is None or not self.host.is_running:
        self.connect_button.setText("Connect")
    QMessageBox.warning(self, "Sun upper machine error", message)
```

**修复方案 B**：将按钮状态更新移到 `on_status` 槽函数中，由线程的 `status_changed` 信号触发，而不是在 `toggle_connection` 中提前设置。

---

## 🟡 设计问题（建议修复）

### Design-1：`TelemetryParser` 对命令帧处理效率低

**文件**：`sun_protocol.py` 第 159–198 行

**现象**：当字节流中混有命令帧（`msg_type=0x80`）时，解析器会将 `cmd_id` 误读为 `payload_len`，计算出错误的帧长，然后 CRC 校验失败，增加 `frame_error_count`。虽然最终能恢复，但浪费了 CRC 计算和多次无效搜索。

**建议**：在计算 `frame_len` 之前先检查 `msg_type`，非遥测帧直接跳过。

```python
# TelemetryParser.feed() 中，line 170 之后添加：
if len(self._buffer) < 6:
    break

# 添加 msg_type 提前检查
msg_type = self._buffer[3]
if msg_type != MSG_TYPE_TELEMETRY:
    self.frame_error_count += 1
    del self._buffer[:2]  # 跳过 SOF，继续搜索下一帧
    continue

payload_len = self._buffer[5]
```

---

### Design-2：`on_error` 弹窗可能叠加

**文件**：`sun_gui.py` 第 269–272 行

**现象**：`on_error` 每次都弹 `QMessageBox.warning`。如果错误频繁发生（如串口反复断连），弹窗会叠加卡住界面。

**建议**：添加错误节流机制。

```python
def __init__(self):
    # ...
    self._last_error_dialog_time = 0.0
    self._error_dialog_interval_s = 5.0  # 5秒内最多弹一次

def on_error(self, message: str) -> None:
    self.append_event(f"ERROR: {message}")
    self.statusBar().showMessage(f"ERROR: {message}")
    import time
    now = time.monotonic()
    if now - self._last_error_dialog_time >= self._error_dialog_interval_s:
        self._last_error_dialog_time = now
        QMessageBox.warning(self, "Sun upper machine error", message)
```

---

### Design-3：`sun_logger.py` 每帧 flush 影响高频性能

**文件**：`sun_logger.py` 第 97 行

**现象**：当前每写一行 CSV 就 `flush()` 一次。10Hz 下没问题，但 50Hz+ 可能影响写入性能。软件方案文档建议每 10 行 flush 一次。

**建议**：

```python
class SunCsvLogger:
    FLUSH_INTERVAL = 10  # 每10行flush一次

    def __init__(self):
        # ... 原有字段
        self._rows_since_flush = 0

    def write(self, telemetry, stats, calibration):
        # ... 原有写入逻辑（去掉每行的 flush）
        self._writer.writerow(row)
        self.rows_written += 1
        self._rows_since_flush += 1
        if self._rows_since_flush >= self.FLUSH_INTERVAL:
            self._handle.flush()
            self._rows_since_flush = 0
```

注意：`stop()` 中已有 `flush()`，不受影响。

---

### Design-4：`SerialThread` 读取策略效率低

**文件**：`sun_host.py` 第 104 行

**现象**：`in_waiting` 为 0 时只读 1 字节，导致系统调用频繁。

**建议**：

```python
# 当前
waiting = getattr(self._serial, "in_waiting", 0) or 1
data = self._serial.read(waiting)

# 改为：保证至少读一些，但不要读太多
waiting = getattr(self._serial, "in_waiting", 0)
read_size = max(waiting, 64)  # 最少读64字节
data = self._serial.read(read_size)
```

或者用更保守的方式：

```python
waiting = getattr(self._serial, "in_waiting", 0)
if waiting > 0:
    data = self._serial.read(waiting)
else:
    data = self._serial.read(1)  # 无数据时只读1字节，等待timeout返回
```

---

### Design-5：缺少数据超时检测

**文件**：`sun_gui.py`

**现象**：软件方案第 11 节明确要求"长时间无数据时状态显示超时"。当前代码没有实现：串口打开后如果一直收不到数据，界面不会有任何提示。

**建议**：在 `SunMainWindow` 中添加一个 QTimer，定期检查最近一次收到遥测的时间。

```python
def __init__(self):
    # ...
    self._last_telemetry_time = 0.0
    self._timeout_timer = QTimer(self)
    self._timeout_timer.timeout.connect(self._check_timeout)
    self._timeout_timer.start(2000)  # 每2秒检查一次
    self._data_timeout_s = 5.0       # 5秒无数据视为超时

def on_telemetry(self, telemetry):
    import time
    self._last_telemetry_time = time.monotonic()
    # ... 原有逻辑

def _check_timeout(self):
    if not self.host.is_running:
        return
    import time
    if self._last_telemetry_time > 0 and time.monotonic() - self._last_telemetry_time > self._data_timeout_s:
        self.statusBar().showMessage("WARNING: no telemetry data for 5 seconds")
```

---

### Design-6：缺少连接状态颜色指示

**文件**：`sun_gui.py`

**现象**：软件方案第 22.2 节要求用灰/黄/绿/橙/红颜色指示连接状态，当前只有文字。

**建议**：在连接控制区添加一个状态指示灯 QLabel，通过 QSS 设置背景色：

```python
# 在 _build_connection_box 中添加
self.status_indicator = QLabel("●")
self.status_indicator.setFixedSize(24, 24)
self.status_indicator.setAlignment(Qt.AlignCenter)

# 状态更新函数
def _update_connection_indicator(self, state: str):
    colors = {
        "disconnected": "#9E9E9E",  # 灰色
        "connected_no_data": "#FFC107",  # 黄色
        "receiving": "#4CAF50",  # 绿色
        "crc_errors": "#FF9800",  # 橙色
        "timeout": "#F44336",  # 红色
    }
    color = colors.get(state, "#9E9E9E")
    self.status_indicator.setStyleSheet(
        f"color: {color}; font-size: 18px; font-weight: bold;"
    )
```

---

### Design-7：CSV 中缺少 `rx`/`ry`/`signal_sum` 字段

**文件**：`sun_logger.py`

**现象**：软件方案第 23 节和扩展字段列表中建议将 `rx`、`ry`、`signal_sum` 写入 CSV。当前 `SunMonitorWidget` 显示了这些值，但 CSV 中没有记录。标定后处理时需要这些特征量。

**建议**：在 `CSV_FIELDS` 中添加这三个字段：

```python
CSV_FIELDS = [
    "pc_time_iso",
    "pc_time_ms",
    "seq",
    "node_id",
    "timestamp_ms",
    "adc_vax1",
    "adc_vax2",
    "adc_vay1",
    "adc_vay2",
    "alpha_deg",
    "beta_deg",
    "temp_c",
    "sun_present",
    "saturation_flag",
    "status_word",
    "valid_flag",
    "signal_sum",    # ← 新增
    "rx",            # ← 新增
    "ry",            # ← 新增
    "frame_rate_hz",
    "drop_count",
    "crc_error_count",
    "alpha_ref_deg",
    "beta_ref_deg",
    "test_point",
    "comment",
]
```

同时在 `write()` 方法中添加对应行：

```python
"signal_sum": str(telemetry.signal_sum),
"rx": f"{telemetry.rx:.6f}",
"ry": f"{telemetry.ry:.6f}",
```

---

## 🟢 小问题 / 改进建议

### Minor-1：`closeEvent` 中信号可能在窗口销毁后到达

**文件**：`sun_gui.py` 第 302–305 行

**建议**：在 `closeEvent` 中先断开信号再停止 host：

```python
def closeEvent(self, event):
    # 先断开信号，防止窗口销毁后仍有信号到达
    try:
        self.host.telemetry_received.disconnect(self.on_telemetry)
        self.host.stats_updated.disconnect(self.on_stats)
        self.host.status_changed.disconnect(self.on_status)
        self.host.error_occurred.disconnect(self.on_error)
    except TypeError:
        pass  # 信号未连接时 disconnect 会抛 TypeError
    self.host.stop()
    self.logger.stop()
    event.accept()
```

---

### Minor-2：曲线刷新可改为定时器驱动

**文件**：`sun_monitor.py` 第 141–142 行

**现象**：当前每收到一帧就刷新全部曲线。软件方案建议用 QTimer 定时刷新（如 100ms 一次），在高频数据下更稳定。

**建议**：

```python
def __init__(self, parent=None, max_points=600):
    # ...
    self._pending_update = False
    self._refresh_timer = QTimer(self)
    self._refresh_timer.timeout.connect(self._refresh_plots)
    self._refresh_timer.start(100)  # 100ms 刷新一次

def update_telemetry(self, telemetry, stats):
    # ... 更新数值标签和状态字（这部分保留即时更新）
    # 只标记需要刷新曲线，不再立即调用 _refresh_plots
    self._append_plot_data(telemetry)
    # _refresh_plots 由定时器驱动
```

---

### Minor-3：缺少 `requirements.txt`

**建议**：在项目根目录创建 `requirements.txt`：

```
PyQt5>=5.15
pyqtgraph>=0.12
pyserial>=3.5
```

---

### Minor-4：`sun_monitor.py` 中 `QWidget | None` 语法兼容性

**文件**：`sun_monitor.py` 第 22 行

**现象**：`parent: QWidget | None = None` 使用 Python 3.10+ 联合类型语法。虽然 `from __future__ import annotations` 使其作为注解可用，但如果需要在 Python 3.7–3.9 运行时做 `isinstance()` 检查会报错。

**建议**：改为 `Optional[QWidget]`：

```python
from typing import Optional

class SunMonitorWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None, max_points: int = 600) -> None:
```

---

## 📝 文档问题

### Doc-1：软件方案中 `payload_len` 数值有误

**文件**：`太阳敏上位机软件方案.md` 第 7.2 节

**现象**：文档写 `payload_len` 建议为 **28**，但实际遥测帧字段合计：

```
seq(2) + timestamp_ms(4) + adc_vax1(2) + adc_vax2(2) + adc_vay1(2) + adc_vay2(2)
+ alpha_cdeg(2) + beta_cdeg(2) + temp_centi_c(2) + sun_present(1) + saturation_flag(1) + status_word(2)
= 24 字节
```

代码中 `TELEMETRY_PAYLOAD_LEN = 24` 是**正确的**，帧总长 32 字节也不变。文档应将 `payload_len` 从 28 改为 **24**。

---

### Doc-2：建议添加通信协议 ICD 文档

软件方案第 12 节和第 29 节多次提到需要与固件工程师确认协议细节，并建议形成 `太阳敏通信协议ICD.md`。当前代码中的协议是上位机侧推荐的，固件侧尚未对齐。建议尽快整理一页 ICD 文档供双方确认。

---

## ✅ 审查中确认的良好实践

以下方面做得好，后续开发应继续保持：

1. **分层架构**：protocol / models / host / logger / monitor / gui 各司其职，耦合度低
2. **协议设计**：CRC-16/Modbus + 帧头搜索 + 字节流解析器，正确处理断帧、粘包、噪声
3. **模拟器全链路验证**：模拟器输出经过 `pack_telemetry` → `TelemetryParser` 完整协议栈
4. **CSV 记录**：字段设计完整，UTF-8-BOM 编码，标定上下文随帧记录
5. **线程安全**：串口接收在 QThread 中，通过 Qt signal 更新 UI
6. **pyserial 守卫导入**：未安装时模拟器仍可运行
7. **单元测试**：覆盖 CRC、断帧拼接、粘包、噪声、CRC 错误、丢帧 wraparound、命令打包

---

## 修复优先级总结

| 优先级 | 编号 | 问题 | 工作量 |
|---:|---|---|---|
| P0 | Bug-1 | drop_frame 多丢一帧 | 5 分钟 |
| P0 | Bug-2 | 连接失败按钮状态不回滚 | 10 分钟 |
| P1 | Design-1 | 命令帧解析效率 | 10 分钟 |
| P1 | Design-2 | 错误弹窗叠加 | 10 分钟 |
| P1 | Design-5 | 数据超时检测 | 15 分钟 |
| P1 | Design-7 | CSV 缺 rx/ry/signal_sum | 10 分钟 |
| P2 | Design-3 | flush 策略优化 | 5 分钟 |
| P2 | Design-4 | 串口读取效率 | 5 分钟 |
| P2 | Design-6 | 连接状态颜色指示 | 15 分钟 |
| P2 | Minor-1 | closeEvent 信号断开 | 10 分钟 |
| P2 | Minor-2 | 曲线定时刷新 | 15 分钟 |
| P3 | Minor-3 | requirements.txt | 2 分钟 |
| P3 | Minor-4 | 类型注解兼容性 | 5 分钟 |
| P3 | Doc-1 | payload_len 文档修正 | 2 分钟 |
| P3 | Doc-2 | 通信协议 ICD 文档 | 独立任务 |
