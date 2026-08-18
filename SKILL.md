---
name: wechat-send
description: >-
  一键给微信指定联系人发送消息。基于 desktop-control skill（PyAutoGUI + OCR）实现，
  已登录微信的前提下，先用 Ctrl+Alt+W 唤醒微信主界面，OCR 定位搜索框与联系人，
  自动粘贴联系人名 → 点开聊天 → 粘贴消息 → Enter 发送，全程可视化、可拦截。
  触发词：微信发消息、给微信发消息、微信发送、自动发微信、wechat 发送。
agent_created: true
version: 1.0.0
display_name: "微信发送"
display_name_en: "WeChat Send"
description_zh: "一键给微信联系人发消息。"
description_en: "One-click WeChat message sender."
visibility: "public"
---

# 微信发送 (wechat-send v1.0)

一键给微信指定联系人发送消息。基于 `desktop-control` skill 的鼠标/键盘/截图/OCR 能力，**已登录微信**前提下全自动完成唤醒→搜人→发消息的端到端流程。

> ⚠️ **前置条件**：PC 微信客户端**已登录**（手机扫码确认过）。Skill 不会替你登录。

## 调用方式

Agent 直接调用托管 Python 跑脚本：

```bash
PY="C:/Users/zjc/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/zjc/.workbuddy/skills/wechat-send/scripts/wechat_send.py"

# 标准调用
"$PY" "$SK" --contact "行风_F21" --message "今天你的股票要大涨"

# 位置参数（更简洁）
"$PY" "$SK" "行风_F21" "今天你的股票要大涨"

# 关键步骤前人工确认（推荐日常使用）
"$PY" "$SK" --contact "行风_F21" --message "..." --approval

# Dry-run：走完整流程但不实际发送（用于测试）
"$PY" "$SK" --contact "行风_F21" --message "..." --dry-run

# JSON 输出（程序解析）
"$PY" "$SK" --contact "行风_F21" --message "..." --json
```

## 流程（10 步）

| 步骤 | 动作 | 备注 |
|---|---|---|
| 1 | 移鼠标到屏幕中央 (1280, 700) | 避免 PyAutoGUI fail-safe 触发 |
| 2 | 按 Ctrl+Alt+W 唤醒微信主界面 | 全局快捷键，已登录前提下最稳 |
| 3 | 激活微信窗口 | `window activate "微信"` |
| 4 | OCR 找搜索框（位于屏幕左上） | 关键字 "搜索" |
| 5 | 点击搜索框 + 粘贴联系人名 | `clip copy` + `ctrl,v` |
| 6 | OCR 找联系人结果 + 点击 | 关键字 = contact |
| 7 | OCR 找输入框（"发送"按钮上方） | |
| 8 | 点击输入框 + 粘贴消息 | `clip copy` + `ctrl,v` |
| 9 | OCR 验证消息在输入框 | 关键字 = 消息内容 |
| 10 | Enter 发送 + OCR 验证已发送 | 消息应该出现在聊天记录 |

每步有耗时记录（毫秒），失败会抛出异常并附错误信息。

## CLI 参数

| 参数 | 简写 | 说明 |
|---|---|---|
| `contact` (位置参数) | | 联系人名称（昵称/微信名） |
| `message` (位置参数) | | 消息内容 |
| `--contact` | `-c` | 联系人名称（与位置参数二选一） |
| `--message` | `-m` | 消息内容（与位置参数二选一） |
| `--approval` | `-a` | 关键步骤前打印 pause，等 `[y/n]` 确认 |
| `--dry-run` | `-n` | 走完整流程但不实际发送 |
| `--timeout` | `-t` | 步骤超时秒数（默认 30） |
| `--json` | `-j` | 结果以 JSON 输出 |

## 输出

**人类可读**（默认）：
```
✅ 消息已成功发送给 '行风_F21'
```

**JSON 格式**：
```json
{
  "ok": true,
  "contact": "行风_F21",
  "message": "今天你的股票要大涨",
  "steps": [
    {"name": "唤醒微信", "ok": true, "duration_ms": 2100},
    {"name": "激活微信窗口", "ok": true, "duration_ms": 50},
    {"name": "找搜索框", "ok": true, "duration_ms": 1200},
    ...
  ]
}
```

**失败时**：
```json
{
  "ok": false,
  "error": "搜索结果中找不到 'XXX'",
  "steps": [...]
}
```

## 安全约定

1. **微信必须先登录**——本 skill 不替你扫码。第一次使用时您得先手动扫码登录。
2. **联系人名要精确**——微信搜人按昵称/微信号识别，建议用对方在您通讯录里显示的昵称。
3. **默认无审批**——加 `--approval` 在发送前暂停确认，正式使用推荐打开。
4. **失败有明确提示**——任何一步失败会返回原因（比如"搜索结果中找不到 XXX"），不会静默不发。
5. **failsafe 始终开启**——failsafe 按钮（鼠标撞屏幕角落）可随时中止所有操作。

## 典型场景

- "给某某发微信说 XXX"
- "群发消息"（需要先循环单发）
- "微信里某个联系人的消息不见了，帮我重发"（结合 wechat 读取）
- "测试一下微信能不能自动发"（`--dry-run`）

## 依赖

- `desktop-control` skill（已被 import 复用）
  - `DesktopController`（鼠标键盘）
  - `_OCREngine`（rapidocr-onnxruntime，文字识别）
  - `NativeDialog`（消息对话框）
- `pyautogui`（已装）
- `rapidocr-onnxruntime`（已装）

## 踩坑汇编（部署前必读）

- ❌ `app open wechat` / `app open "微信"` → 报"找不到文件"，cmd 路径不识别
- ❌ 桌面微信图标双击 → 不可靠
- ❌ Win11 任务栏左下角"行风_F21 + 微信图标" → 是 Teams 集成聊天快捷，**不是微信**
- ✅ **Ctrl+Alt+W 全局快捷键** 是唤醒已登录微信主界面最稳的方式
- ✅ 鼠标必须先移到中央，否则 PyAutoGUI fail-safe 触发整个进程终止
- ✅ WorkBuddy 窗口在前台时，鼠标点击不传到微信窗口，必须先激活微信

源码：`scripts/wechat_send.py`（约 320 行）。
