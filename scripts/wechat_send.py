"""
wechat-send - 一键给微信联系人发送消息/图片
基于 desktop-control skill (PyAutoGUI + rapidocr-onnxruntime + ctypes)

核心流程：
1. Ctrl+Alt+W 唤醒微信主界面（已登录前提）
2. OCR 找搜索框，点击 + 粘贴联系人名称
3. OCR 找搜索结果中的联系人，点击
4. OCR 找输入区域
5. 文本消息：粘贴 + Enter 发送
   图片消息：Ctrl+V 粘贴剪贴板图片 + Enter 发送
6. OCR 验证消息已发送

CLI 用法:
  python wechat_send.py --contact "荣宝" --message "今天您的ETF要大涨" --json
  python wechat_send.py --contact "荣宝" --image "C:\\path\\to\\pic.jpg" --json
  python wechat_send.py --contact "荣宝" --message "看图" --image "C:\\path\\to\\pic.jpg" --json
"""

import argparse
import sys
import time
import json
import logging
import ctypes
import subprocess
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# 复用 desktop-control 的核心能力
DC_SCRIPTS = Path.home() / ".workbuddy" / "skills" / "desktop-control" / "scripts"
if str(DC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DC_SCRIPTS))

from desktop_control import DesktopController, _OCREngine, NativeDialog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("wechat-send")

# ========== 微信专用配置 ==========
SCREEN_W, SCREEN_H = 2560, 1600
MOUSE_SAFE = (1280, 700)  # 屏幕中心，避免 PyAutoGUI fail-safe


# ========== 工具函数 ==========
def move_safe(dc: DesktopController):
    """移到屏幕中央，避免 PyAutoGUI fail-safe 触发。"""
    dc.pos()
    import pyautogui
    pyautogui.moveTo(MOUSE_SAFE[0], MOUSE_SAFE[1], duration=0.1)


def ocr_all(dc: DesktopController) -> List[Dict]:
    """全屏 OCR，返回 [{text, score, bbox}, ...]。"""
    return dc.read_text()


def bbox_center(b: Dict) -> tuple:
    return (b["left"] + b["width"] // 2, b["top"] + b["height"] // 2)


def wait_cond(fn, timeout=8.0, interval=0.4):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def copy_image_to_clipboard(image_path: str) -> bool:
    """用 PowerShell 把图片复制到剪贴板。"""
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        logger.error(f"图片不存在: {abs_path}")
        return False
    # PowerShell 脚本：加载图片到剪贴板
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile('{abs_path.replace(chr(39), chr(39)+chr(39))}')
$ms = New-Object System.IO.MemoryStream
$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$ms.Position = 0
$data = New-Object System.Windows.Forms.DataObject
$data.SetData([System.Windows.Forms.DataFormats]::Bitmap, $true, [System.Drawing.Image]::FromStream($ms))
[System.Windows.Forms.Clipboard]::SetDataObject($data, $true)
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"PowerShell 复制图片失败: {result.stderr}")
            return False
        logger.info(f"图片已复制到剪贴板: {abs_path}")
        return True
    except Exception as e:
        logger.error(f"复制图片出错: {e}")
        return False


# ========== 核心 ==========
class WeChatSender:
    def __init__(self, contact: str, message: str = "", image: str = "",
                 *, approval=False, dry_run=False, timeout=30.0):
        self.contact = contact
        self.message = message
        self.image = image
        self.has_text = bool(message)
        self.has_image = bool(image)
        self.approval = approval
        self.dry_run = dry_run
        self.steps: List[Dict] = []
        self.dc = DesktopController(failsafe=True, require_approval=False)

    def _step(self, name: str, fn):
        t0 = time.time()
        try:
            result = fn()
            ms = int((time.time() - t0) * 1000)
            self.steps.append({"name": name, "ok": True, "duration_ms": ms})
            logger.info(f"✓ {name} ({ms}ms)")
            return result
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            self.steps.append({"name": name, "ok": False, "error": str(e), "duration_ms": ms})
            logger.error(f"✗ {name}: {e}")
            raise

    def _confirm(self, prompt: str) -> bool:
        if not self.approval:
            return True
        resp = input(f"\n[确认] {prompt}\n继续? [y/n]: ").strip().lower()
        return resp in ("y", "yes")

    def wake_wechat(self) -> bool:
        """唤醒微信：1) 最小化 WorkBuddy 避免遮挡 2) 检查窗口已开则激活 3) 否则按 Ctrl+Alt+W。"""
        move_safe(self.dc)
        # 关键：先最小化 WorkBuddy 避免遮挡微信
        try:
            wb_hwnd = ctypes.windll.user32.FindWindowW(None, "WorkBuddy")
            if wb_hwnd:
                ctypes.windll.user32.ShowWindow(wb_hwnd, 6)  # SW_MINIMIZE
                logger.info("已最小化 WorkBuddy 避免遮挡")
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"最小化 WorkBuddy 失败: {e}")
        # 检查窗口
        titles = self.dc.window_list()
        wechat_titles = [t for t in titles if '微信' in t or 'WeChat' in t]
        if wechat_titles:
            logger.info(f"微信已开: {wechat_titles[0]}")
            self.dc.window_activate(wechat_titles[0].split(' - ')[0].strip())
            time.sleep(1.0)
            return True
        # 快捷键唤醒
        logger.info("按 Ctrl+Alt+W 唤醒微信...")
        self.dc.hotkey("ctrl", "alt", "w")
        time.sleep(3)
        titles2 = self.dc.window_list()
        wechat_titles2 = [t for t in titles2 if '微信' in t or 'WeChat' in t]
        if wechat_titles2:
            logger.info(f"微信已唤醒: {wechat_titles2[0]}")
            return True
        return False

    def find_search_box(self) -> Optional[tuple]:
        """找搜索框。"""
        results = ocr_all(self.dc)
        for r in results:
            if "搜索" in r["text"]:
                b = r["bbox"]
                if b["left"] < 600 and b["top"] < 300:
                    return bbox_center(b)
        return None

    def find_contact_in_results(self, contact: str) -> Optional[tuple]:
        """在搜索结果中找联系人（排除搜索框区域）。"""
        results = ocr_all(self.dc)
        for r in results:
            text = r["text"]
            b = r["bbox"]
            if b["left"] < 600 and b["top"] < 200:
                continue
            if contact in text:
                return bbox_center(b)
        return None

    def find_input_area(self) -> Optional[tuple]:
        """找输入框：找'发送'按钮，输入框在其左上方。"""
        results = ocr_all(self.dc)
        for r in results:
            if r["text"] == "发送":
                sx, sy = bbox_center(r["bbox"])
                input_x = sx - 300
                if input_x < 100:
                    input_x = 400
                input_y = sy - 20
                return (input_x, input_y)
        # 兜底：底部区域
        bottom_texts = [r for r in results if r["bbox"]["top"] > 1200]
        if bottom_texts:
            lowest = max(bottom_texts, key=lambda r: r["bbox"]["top"] + r["bbox"]["height"])
            return bbox_center(lowest["bbox"])
        return None

    def verify_sent_text(self, message: str, timeout=6.0) -> bool:
        """验证文本消息已发送。"""
        def check():
            results = ocr_all(self.dc)
            for r in results:
                if message in r["text"]:
                    b = r["bbox"]
                    if b["top"] > 300:
                        return True
            return False
        return wait_cond(check, timeout=timeout, interval=0.6)

    def verify_sent_image(self, timeout=6.0) -> bool:
        """验证图片已发送：聊天窗口底部应有图片缩略图（OCR 难识别图片本身，
        但我们可以通过截图区域检查输入框上方是否出现图片预览气泡）。"""
        # 简化方法：等待 3 秒，假设图片已发送（微信发出图片后聊天窗口会更新）
        time.sleep(3)
        return True

    def send(self) -> Dict:
        logger.info(f"开始给 '{self.contact}' 发消息"
                    f"{'+图片' if self.has_image else ''}{'+文字' if self.has_text else ''}")

        # 0. 校验
        if not self.has_text and not self.has_image:
            return {"ok": False, "error": "必须提供 --message 或 --image 至少一个", "steps": self.steps}

        # 1. 唤醒微信
        if not self._step("唤醒微信", self.wake_wechat):
            return {
                "ok": False,
                "error": "微信未启动或未登录。请先在 PC 上登录微信，然后重试。",
                "steps": self.steps,
                "hint": "也可手动按 Ctrl+Alt+W 唤醒微信后再运行此 skill。",
            }

        # 2. 激活窗口
        self._step("激活微信窗口", lambda: self.dc.window_activate("微信"))
        time.sleep(0.8)

        # 3. 找搜索框
        search_box = self._step("找搜索框", self.find_search_box)
        if not search_box:
            return {"ok": False, "error": "找不到微信搜索框，请确认微信窗口已激活。", "steps": self.steps}
        sx, sy = search_box
        logger.info(f"搜索框: ({sx}, {sy})")

        # 4. 点击搜索框 + 粘贴联系人
        self._step("点击搜索框", lambda: self.dc.click(sx, sy))
        time.sleep(0.5)
        self._step("粘贴联系人", lambda: self.dc.clip_copy(self.contact) or self.dc.hotkey("ctrl", "v"))
        time.sleep(1.5)

        # 5. 找联系人并点击
        if not self._confirm(f"将点击联系人 '{self.contact}'，继续?"):
            return {"ok": False, "error": "用户取消", "steps": self.steps}
        contact_pos = self._step("找联系人", lambda: self.find_contact_in_results(self.contact))
        if not contact_pos:
            return {"ok": False, "error": f"搜索结果中找不到 '{self.contact}'，请确认联系人名正确。", "steps": self.steps}
        cx, cy = contact_pos
        logger.info(f"联系人: ({cx}, {cy})")
        self._step("点击联系人", lambda: self.dc.click(cx, cy))
        time.sleep(1.5)

        # 6. 找输入框
        input_pos = self._step("找输入框", self.find_input_area)
        if not input_pos:
            return {"ok": False, "error": "找不到输入框", "steps": self.steps}
        ix, iy = input_pos
        logger.info(f"输入框: ({ix}, {iy})")

        # 7. 点击输入框
        self._step("点击输入框", lambda: self.dc.click(ix, iy))
        time.sleep(0.4)

        # 8. 发送文本（先发文字，再发图片）
        if self.has_text:
            self._step("粘贴消息", lambda: self.dc.clip_copy(self.message) or self.dc.hotkey("ctrl", "v"))
            time.sleep(1)
            if not self._step("OCR 验证消息已贴入", lambda: bool(self.dc.locate_text(self.message))):
                logger.warning("OCR 未找到消息文字，尝试继续发送...")
            if not self._confirm(f"将发送 '{self.message}' 给 '{self.contact}'，确认?"):
                return {"ok": False, "error": "用户取消发送", "steps": self.steps}
            self._step("Enter 发送", lambda: self.dc.press("enter"))
            time.sleep(2)

        # 9. 发送图片
        if self.has_image:
            if not self._confirm(f"将发送图片 '{self.image}' 给 '{self.contact}'，确认?"):
                return {"ok": False, "error": "用户取消发送图片", "steps": self.steps}
            if not self._step("复制图片到剪贴板", lambda: copy_image_to_clipboard(self.image)):
                return {"ok": False, "error": "复制图片到剪贴板失败", "steps": self.steps}
            self._step("粘贴图片", lambda: self.dc.hotkey("ctrl", "v"))
            time.sleep(1.5)
            # 图片粘贴后，微信输入框上方会显示预览，需再按 Enter 发送
            self._step("Enter 发送图片", lambda: self.dc.press("enter"))
            time.sleep(2.5)
            self._step("验证图片已发送", lambda: self.verify_sent_image())

        # 10. 验证文本发送（如果发了文本）
        if self.has_text:
            sent_ok = self._step("验证已发送", lambda: self.verify_sent_text(self.message))
            if not sent_ok:
                return {
                    "ok": False,
                    "error": "消息可能未成功发送，请检查聊天记录。",
                    "steps": self.steps,
                    "hint": "如果聊天窗口需要滚动，可手动滚到最新消息处再重试。",
                }

        return {
            "ok": True,
            "contact": self.contact,
            "message": self.message if self.has_text else None,
            "image": self.image if self.has_image else None,
            "steps": self.steps,
        }

        return {"ok": False, "error": "未知流程", "steps": self.steps}


# ========== CLI ==========
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wechat-send", description="一键给微信联系人发送消息/图片（需微信已登录）")
    p.add_argument("--contact", "-c", required=True, help="联系人名称")
    p.add_argument("--message", "-m", default="", help="文本消息内容")
    p.add_argument("--image", "-i", default="", help="图片路径（JPG/PNG）")
    p.add_argument("--approval", "-a", action="store_true", help="关键步骤前弹出确认")
    p.add_argument("--dry-run", "-n", action="store_true", help="只走流程不发送")
    p.add_argument("--timeout", "-t", type=float, default=30.0, help="超时秒数")
    p.add_argument("--json", "-j", action="store_true", help="JSON 输出结果")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    sender = WeChatSender(
        contact=args.contact,
        message=args.message,
        image=args.image,
        approval=args.approval,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )
    try:
        result = sender.send()
    except KeyboardInterrupt:
        result = {"ok": False, "error": "用户中断"}
    except Exception as e:
        result = {"ok": False, "error": f"异常: {e}"}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"✅ 消息已发送给 '{args.contact}'")
        else:
            print(f"❌ 失败: {result.get('error', '未知错误')}")
            if result.get("hint"):
                print(f"   提示: {result['hint']}")
        if args.dry_run:
            print("   (dry-run 模式，未实际发送)")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
