/**
 * 已登录且邮箱未绑定/未验证时，在主页与活动列表弹窗建议绑定邮箱（每次进入均提示）。
 */
(function (global) {
  const VERIFY_URL = "/user/verify_email";

  function showModal() {
    if (!global.AppModal) return;
    const modal = global.AppModal.create({
      title: "建议绑定邮箱",
      html: "<p>绑定并验证邮箱后，可用于登录与找回密码。</p>",
      actions: [
        {
          label: "稍后再说",
          onClick: function (api) { api.destroy(); },
        },
        {
          label: "前往绑定",
          primary: true,
          onClick: function () { global.location.href = VERIFY_URL; },
        },
      ],
    });
    modal.open();
  }

  async function fetchMe() {
    if (!global.ClockTowerAuth) return null;
    await global.ClockTowerAuth.establishSessionFromStoredToken();
    try {
      const res = await global.ClockTowerAuth.authFetch("/user/me", {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  function needsEmailBind(me) {
    if (!me || !me.username) return false;
    if (!me.email) return true;
    return !me.email_verified;
  }

  async function maybePromptBindEmail() {
    try {
      localStorage.removeItem("clocktower_skip_email_prompt");
    } catch (e) {}
    const me = await fetchMe();
    if (!needsEmailBind(me)) return;
    showModal();
  }

  global.ClockTowerEmailPrompt = {
    maybePromptBindEmail,
    needsEmailBind,
  };

  document.addEventListener("DOMContentLoaded", maybePromptBindEmail);
})(typeof window !== "undefined" ? window : globalThis);
