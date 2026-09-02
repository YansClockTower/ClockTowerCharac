/**
 * 已登录且邮箱未绑定/未验证时，在主页与活动列表弹窗建议绑定邮箱（每次进入均提示）。
 */
(function (global) {
  const VERIFY_URL = "/user/verify_email";

  function ensureStyles() {
    /* styles live in app/static/css/site.css */
  }

  function showModal() {
    ensureStyles();
    const backdrop = document.createElement("div");
    backdrop.className = "email-bind-prompt-backdrop";
    backdrop.innerHTML = `
      <div class="email-bind-prompt-card" role="dialog" aria-modal="true" aria-labelledby="email-bind-prompt-title">
        <h3 id="email-bind-prompt-title">建议绑定邮箱</h3>
        <p>绑定并验证邮箱后，可用于登录与找回密码。</p>
        <div class="email-bind-prompt-actions">
          <button type="button" class="email-bind-prompt-secondary" data-action="dismiss">稍后再说</button>
          <button type="button" class="email-bind-prompt-primary" data-action="go">前往绑定</button>
        </div>
      </div>
    `;

    function close() {
      backdrop.remove();
    }

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) close();
    });

    backdrop.querySelector('[data-action="go"]').addEventListener("click", () => {
      global.location.href = VERIFY_URL;
    });

    backdrop.querySelector('[data-action="dismiss"]').addEventListener("click", () => {
      close();
    });

    document.body.appendChild(backdrop);
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
