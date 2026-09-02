"""通过 Resend 官方 SDK 发送验证码邮件。配置来自 config.txt。"""

from __future__ import annotations

from app.models.config import get_config


def _api_key() -> str:
    try:
        return str(get_config("resend_api_key") or "").strip()
    except KeyError:
        return ""


def _from_address() -> str:
    try:
        return str(get_config("mail_from") or "").strip() or "onboarding@resend.dev"
    except KeyError:
        return "onboarding@resend.dev"


def send_email(to_email, subject, text, html=None):
    """发送一封邮件。未配置 API Key 时只打印到控制台，便于本地调试。"""
    api_key = _api_key()
    if not api_key or api_key == "re_xxxxxxxxx":
        print(f"[mailer] 未配置 resend_api_key（secrets.txt），邮件未真正发出 -> {to_email}")
        print(f"[mailer] 主题: {subject}\n{text}")
        return True, "dev-print"

    import resend

    resend.api_key = api_key
    params = {
        "from": _from_address(),
        "to": to_email,
        "subject": subject,
        "html": html or f"<p>{text}</p>",
    }
    if text:
        params["text"] = text

    try:
        result = resend.Emails.send(params)
        email_id = result.get("id") if isinstance(result, dict) else str(result)
        return True, email_id
    except Exception as exc:
        print(f"[mailer] Resend 发送失败: {exc}")
        return False, str(exc)


def send_verification_code(to_email, code, purpose="register"):
    labels = {
        "register": "注册",
        "bind": "绑定邮箱",
        "reset": "重设密码",
    }
    label = labels.get(purpose, "验证")
    subject = f"布鸽桌游协会 · {label}验证码"
    text = f"你的{label}验证码是 {code}，10 分钟内有效。如果不是你本人操作，请忽略此邮件。"
    html = f"<p>你的{label}验证码是 <strong>{code}</strong>，10 分钟内有效。</p>"
    return send_email(to_email, subject, text, html)
