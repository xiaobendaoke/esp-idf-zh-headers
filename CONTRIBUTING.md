# 贡献指南 (Contributing Guide)

感谢你对 `esp-idf-zh-headers` 的关注与贡献！无论是修正某条术语翻译、补充芯片专属头文件词条，还是改进 CLI 工具，都非常欢迎提交 Pull Request。

---

## 一、 如何修正或优化已有翻译

所有翻译词条均按 ESP-IDF 组件名清晰拆分在 `translations/components/<component>.json` 中（例如 I2C 驱动位于 `translations/components/esp_driver_i2c.json`，FreeRTOS 位于 `translations/components/freertos.json`）。

每个 JSON 文件的结构如下：

```json
{
  "component": "esp_driver_i2c",
  "headers": [
    "components/esp_driver_i2c/include/driver/i2c_master.h",
    "components/esp_driver_i2c/include/driver/i2c_slave.h",
    "components/esp_driver_i2c/include/driver/i2c_types.h"
  ],
  "entry_count": 97,
  "entries": {
    "/*!< SCL GPIO number */": "/*!< SCL GPIO 引脚编号 */"
  }
}
```

### 翻译修改红线（CI 自动强制检查）

修改 `"entries"` 中的中文值（Value）时，**请勿修改英文键（Key）**，并严格遵守以下 5 条规则：

1. **定界符严格一致**：原文以 `/**`、`/**<`、`/*!<`、`///` 或 `///<` 开头，译文必须以完全相同的符号开头；块注释必须以 `*/` 结尾，且正文中绝不能提前出现 `*/`。
2. **保留 `@param` 参数名与 Doxygen 命令**：`@brief`、`@param[in] bus_handle`、`@return`、`@note`、`@warning`、`@attention`、`@retval` 等标签及紧跟在 `@param` 后的英文参数名标识符（如 `bus_handle`）必须原样保留，否则 IDE 无法将参数说明与函数签名绑定。
3. **不改动示例代码中的 C 语句**：`@code ... @endcode` 块内的 C 代码标识符与语法保持不变（仅可翻译其中的代码注释）。
4. **单行注释禁止换行**：`//`、`///`、`///<` 开头的单行注释译文中严禁包含 `\n`、`\r` 或行尾续行符 `\`。
5. **编码规范**：所有 `.json` 与 `.py` 文件必须使用 **UTF-8 无 BOM** 编码，并以 LF（`\n`）作为行结束符。

---

## 二、 本地自检步骤（提交 PR 前必跑）

修改完成后，请在仓库根目录依次执行以下两条命令，确保输出零错误：

```bash
# 1. 校验全部组件 JSON 字典语法与 Doxygen 规则
python idf_zh.py validate

# 2. 运行完整单元测试套件
python -m unittest discover -s tests -v
```

---

## 三、 术语参考约定

为保证跨组件阅读体验一致，建议优先采用乐鑫《ESP-IDF 编程指南》中文版常用译法：

| 英文术语 | 推荐中文译法 |
| :--- | :--- |
| Handle | 句柄 |
| Callback | 回调函数 |
| ISR (Interrupt Service Routine) | 中断服务程序 (ISR) |
| Glitch filter | 毛刺滤波器 |
| Transaction | 传输事务 |
| Semaphore / Mutex | 信号量 / 互斥锁 |
| Event Group | 事件组 |
| Task Notification | 任务通知 |
| Provisioning | 配网 |
| NVS (Non-Volatile Storage) | 非易失性存储 (NVS) |

---

## 四、 开源许可协议

提交 Pull Request 即表示你同意将所提交的修改按本仓库的 [Apache License 2.0](./LICENSE) 协议进行开源授权。
