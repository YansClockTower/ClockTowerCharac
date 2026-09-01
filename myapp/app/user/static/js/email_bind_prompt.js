/**
 * 已登录且邮箱未验证时，弹窗建议绑定邮箱（可跳过，localStorage 标记）。
 */
(function (global) {
  const SKIP_KEY = "clocktower_skip_email_prompt";
  const VERIFY_URL = "/user/verify_email";

  function ensureStyles() {
    if (document.getElementById("email-bind-prompt-styles")) return;
    const style = document.createElement("style");
    style.id = "email-bind-prompt-styles";
    style.textContent = `
      .email-bind-prompt-backdrop {
        position: fixed;
        inset: 0;
        z-index: 2000;
        background: rgba(0, 0, 0, 0.45);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 16px;
        box-sizing: border-box;
      }
      .email-bind-prompt-card {
        width: 100%;
        max-width: 360px;
        background: #fff;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
      }
      .email-bind-prompt-card h3 {
        margin: 0 0 10px;
        font-size: 1.15rem;
      }
      .email-bind-prompt-card p {
        margin: 0 0 16px;
        color: #555;
        line-height: 1.5;
        font-size: 0.95rem;
      }
      .email-bind-prompt-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
      }
      .email-bind-prompt-actions button {
        border: none;
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 0.95rem;
        cursor: pointer;
      }
      .email-bind-prompt-primary {
        background: #007bff;
        color: #fff;
      }
      .email-bind-prompt-secondary {
        background: #f1f3f5;
        color: #333;
      }
    `;
    document.head.appendChild(style);
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
          <button type="button" class="email-bind-prompt-secondary" data-action="skip">暂时忽略</button>
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

    backdrop.querySelector('[data-action="skip"]').addEventListener("click", async () => {
      try {
        localStorage.setItem(SKIP_KEY, "1");
      } catch (e) {}
      if (global.ClockTowerAuth) {
        try {
          await global.ClockTowerAuth.authFetch("/user/skip_email_prompt", { method: "POST" });
        } catch (e) {}
      }
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

  async function maybePromptBindEmail() {
    try {
      if (localStorage.getItem(SKIP_KEY)) return;
    } catch (e) {}
    const me = await fetchMe();
    if (!me || !me.username) return;
    if (me.email_verified) return;
    showModal();
  }

  global.ClockTowerEmailPrompt = {
    SKIP_KEY,
    maybePromptBindEmail,
  };

  document.addEventListener("DOMContentLoaded", maybePromptBindEmail);
})(typeof window !== "undefined" ? window : globalThis);
