# -*- coding: utf-8 -*-
"""WeChat QR Code Login

独立的微信扫码登录模块，通过 iLink Bot API 完成 QR 扫码认证并获取 bot_token。
无需依赖任何外部插件（如 openclaw-weixin），完全自包含。

API 协议:
  1. GET /ilink/bot/get_bot_qrcode?bot_type=3  → {qrcode, qrcode_img_content}
  2. GET /ilink/bot/get_qrcode_status?qrcode=<qr>  (35s long-poll)
     → status: "wait" | "scaned" | "confirmed" | "expired"
     → on "confirmed": {bot_token, ilink_bot_id, baseurl, ilink_user_id}
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
MAX_QR_REFRESHES = 3
OVERALL_TIMEOUT = 480  # 8 分钟总超时
POLL_TIMEOUT = 35  # 单次长轮询超时 (秒)
HTTP_CLIENT_TIMEOUT = 40  # httpx 客户端超时 (比 POLL_TIMEOUT 略大)

# QR 状态
STATUS_WAIT = "wait"
STATUS_SCANNED = "scaned"  # API 原文如此 (少一个 n)
STATUS_CONFIRMED = "confirmed"
STATUS_EXPIRED = "expired"

# 账号信息持久化目录
DEFAULT_ACCOUNTS_DIR = os.path.expanduser("~/.agent-nexus/wechat_accounts")


# ── 异常类 ──────────────────────────────────────────────────────────────────

class LoginError(Exception):
    """登录过程中的通用异常"""
    pass


class LoginTimeoutError(LoginError):
    """登录超时"""
    pass


class QRCodeExpiredError(LoginError):
    """QR 码已过期且达到最大刷新次数"""
    pass


# ── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class LoginResult:
    """扫码登录成功后的结果"""
    bot_token: str
    ilink_bot_id: str
    base_url: str
    ilink_user_id: str


# ── 主类 ────────────────────────────────────────────────────────────────────

class WeChatQRLogin:
    """微信 QR 扫码登录

    使用同步 httpx 客户端（CLI 上下文，非 async）。
    通过回调函数与调用方通信：
      - on_qr(qr_text: str)  : 当需要展示 QR 码时调用
      - on_status(status: str, message: str) : 状态变化通知
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ── 公开方法 ──────────────────────────────────────────────────────────

    def login(
        self,
        on_qr: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, str], None]] = None,
    ) -> LoginResult:
        """执行完整的 QR 扫码登录流程

        Args:
            on_qr: 当 QR 码准备好时的回调，参数为终端可打印的 QR 文本
            on_status: 状态变化回调，参数为 (status_code, 人类可读消息)

        Returns:
            LoginResult: 包含 bot_token 等认证信息

        Raises:
            LoginError: 登录失败
            LoginTimeoutError: 总超时
            QRCodeExpiredError: QR 码过期且刷新次数用尽
        """
        try:
            import httpx
        except ImportError:
            raise LoginError(
                "WeChat login requires 'httpx'. Install with: pip install httpx"
            )

        start_time = time.monotonic()
        qr_refresh_count = 0

        with httpx.Client(timeout=httpx.Timeout(HTTP_CLIENT_TIMEOUT)) as client:
            while qr_refresh_count <= MAX_QR_REFRESHES:
                # 检查总超时
                elapsed = time.monotonic() - start_time
                if elapsed >= OVERALL_TIMEOUT:
                    raise LoginTimeoutError(
                        f"登录超时 ({OVERALL_TIMEOUT}s)，请重新执行 'anexus login wechat'"
                    )

                # 获取 QR 码
                qr_refresh_count += 1
                if self._notify_status(on_status, "fetching_qr",
                                       f"正在获取二维码... ({qr_refresh_count}/{MAX_QR_REFRESHES + 1})"):
                    pass

                try:
                    qrcode_value, qrcode_img_content = self._fetch_qrcode(client)
                except Exception as e:
                    raise LoginError(f"获取二维码失败: {e}")

                # 渲染并展示 QR 码
                qr_text = self.render_qr_terminal(qrcode_img_content)
                if on_qr:
                    on_qr(qr_text)

                self._notify_status(on_status, STATUS_WAIT,
                                    "请使用微信扫描上方二维码")

                # 轮询状态
                result = self._poll_until_done(
                    client, qrcode_value, on_status, start_time
                )

                if result is not None:
                    # 登录成功
                    self._notify_status(
                        on_status, "success",
                        f"登录成功! (user: {result.ilink_user_id})"
                    )
                    # 持久化账号信息
                    self._save_account(result)
                    return result

                # QR 码过期，继续循环刷新
                if qr_refresh_count <= MAX_QR_REFRESHES:
                    self._notify_status(
                        on_status, STATUS_EXPIRED,
                        f"二维码已过期，正在刷新... ({qr_refresh_count}/{MAX_QR_REFRESHES})"
                    )

        raise QRCodeExpiredError(
            f"二维码已过期 {MAX_QR_REFRESHES + 1} 次，请重新执行 'anexus login wechat'"
        )

    # ── API 调用 ──────────────────────────────────────────────────────────

    def _fetch_qrcode(self, client) -> Tuple[str, str]:
        """获取 QR 码

        Returns:
            (qrcode_value, qrcode_img_content) 元组
        """
        url = f"{self.base_url}/ilink/bot/get_bot_qrcode"
        resp = client.get(url, params={"bot_type": "3"})
        resp.raise_for_status()
        data = resp.json()

        qrcode_value = data.get("qrcode", "")
        qrcode_img_content = data.get("qrcode_img_content", "")

        if not qrcode_value or not qrcode_img_content:
            raise LoginError(
                f"API 返回的二维码数据无效: "
                f"qrcode={'有' if qrcode_value else '无'}, "
                f"qrcode_img_content={'有' if qrcode_img_content else '无'}"
            )

        return qrcode_value, qrcode_img_content

    def _poll_qr_status(self, client, qrcode: str) -> dict:
        """长轮询 QR 码状态

        Returns:
            API 响应 dict，包含 status 字段
        """
        url = f"{self.base_url}/ilink/bot/get_qrcode_status"
        headers = {"iLink-App-ClientVersion": "1"}

        try:
            resp = client.get(
                url,
                params={"qrcode": qrcode},
                headers=headers,
                timeout=HTTP_CLIENT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            # 长轮询超时是正常的
            import httpx as _httpx
            try:
                raise
            except _httpx.TimeoutException:
                return {"status": STATUS_WAIT}
            except Exception:
                raise

    def _poll_until_done(
        self,
        client,
        qrcode: str,
        on_status: Optional[Callable],
        start_time: float,
    ) -> Optional[LoginResult]:
        """持续轮询直到确认/过期/超时

        Returns:
            LoginResult: 如果登录成功
            None: 如果 QR 码过期 (需要刷新)

        Raises:
            LoginTimeoutError: 总超时
            LoginError: 其他错误
        """
        import httpx as _httpx

        last_status = ""

        while True:
            # 检查总超时
            elapsed = time.monotonic() - start_time
            if elapsed >= OVERALL_TIMEOUT:
                raise LoginTimeoutError(
                    f"登录超时 ({OVERALL_TIMEOUT}s)，请重新执行 'anexus login wechat'"
                )

            try:
                data = self._poll_qr_status(client, qrcode)
            except _httpx.TimeoutException:
                # 长轮询超时，继续
                continue
            except Exception as e:
                logger.warning(f"QR 状态轮询异常: {e}")
                time.sleep(2)
                continue

            status = data.get("status", STATUS_WAIT)

            # 状态变化时通知
            if status != last_status:
                last_status = status

                if status == STATUS_SCANNED:
                    self._notify_status(
                        on_status, STATUS_SCANNED,
                        "已扫码，请在手机上确认登录"
                    )
                elif status == STATUS_CONFIRMED:
                    # 登录成功
                    bot_token = data.get("bot_token", "")
                    if not bot_token:
                        raise LoginError("服务器返回 confirmed 但未包含 bot_token")

                    return LoginResult(
                        bot_token=bot_token,
                        ilink_bot_id=data.get("ilink_bot_id", ""),
                        base_url=data.get("baseurl", self.base_url),
                        ilink_user_id=data.get("ilink_user_id", ""),
                    )
                elif status == STATUS_EXPIRED:
                    # QR 过期，返回 None 触发刷新
                    return None

    # ── QR 渲染 ───────────────────────────────────────────────────────────

    @staticmethod
    def render_qr_terminal(qr_content: str) -> str:
        """将 QR 码内容渲染为终端可打印的文本

        使用 qrcode 包生成 Unicode block 字符的 QR 码。
        如果 qrcode 包不可用，回退到显示原始 URL。

        Args:
            qr_content: QR 码内容字符串 (URL)

        Returns:
            终端可打印的 QR 码文本
        """
        try:
            import qrcode as qr_lib

            qr = qr_lib.QRCode(
                version=1,
                error_correction=qr_lib.constants.ERROR_CORRECT_L,
                box_size=1,
                border=1,
            )
            qr.add_data(qr_content)
            qr.make(fit=True)

            # 使用 Unicode block 字符渲染
            # █ = 黑色, ' ' = 白色
            # 每两行合并为一行，使用 ▀ ▄ █ ' ' 四种字符
            modules = qr.get_matrix()
            lines = []

            for r in range(0, len(modules), 2):
                line = ""
                for c in range(len(modules[0])):
                    top = modules[r][c] if r < len(modules) else False
                    bottom = modules[r + 1][c] if r + 1 < len(modules) else False

                    if top and bottom:
                        line += "█"
                    elif top and not bottom:
                        line += "▀"
                    elif not top and bottom:
                        line += "▄"
                    else:
                        line += " "

                lines.append(line)

            return "\n".join(lines)

        except ImportError:
            # qrcode 包不可用时的回退
            return (
                f"[QR Code]\n"
                f"qrcode 包未安装，请手动访问以下 URL 完成扫码:\n"
                f"{qr_content}\n"
                f"\n"
                f"安装 qrcode 包: pip install qrcode>=7.0"
            )
        except Exception as e:
            return f"[QR 渲染失败: {e}]\n内容: {qr_content}"

    # ── 账号持久化 ─────────────────────────────────────────────────────────

    @staticmethod
    def _save_account(result: LoginResult) -> None:
        """将登录信息持久化到本地文件

        保存到 ~/.agent-nexus/wechat_accounts/<user_id>.json
        """
        try:
            accounts_dir = Path(DEFAULT_ACCOUNTS_DIR)
            accounts_dir.mkdir(parents=True, exist_ok=True)

            user_id = result.ilink_user_id or "default"
            # 文件名安全处理
            safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in user_id)
            filepath = accounts_dir / f"{safe_id}.json"

            account_data = asdict(result)
            account_data["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            filepath.write_text(
                json.dumps(account_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"WeChat account info saved to {filepath}")
        except Exception as e:
            logger.warning(f"Failed to save WeChat account info: {e}")

    # ── 工具方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _notify_status(
        callback: Optional[Callable],
        status: str,
        message: str,
    ) -> bool:
        """安全地调用状态回调"""
        if callback:
            try:
                callback(status, message)
                return True
            except Exception:
                pass
        return False
