/**
 * 与 app.identity.auth.AUTH_TOKEN_LOCAL_STORAGE_KEY 保持一致。
 * 普通浏览器依赖 HttpOnly Cookie；在 Cookie 不可靠的环境（如部分 WebView）由前端写入 localStorage，
 * 并在 fetch 中附带 Authorization: Bearer <JWT>。
 */
(function (global) {
  const AUTH_TOKEN_STORAGE_KEY = "clocktower_auth_token";

  function getStoredAuthToken() {
    try {
      return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredAuthToken(token) {
    try {
      if (token) {
        localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
      }
    } catch (e) {}
  }

  function clearStoredAuthToken() {
    try {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    } catch (e) {}
  }

  /** 合并 JSON 等请求的 headers；FormData 时不要传入 Content-Type。 */
  function authHeaders(base) {
    const headers = Object.assign({}, base || {});
    const t = getStoredAuthToken();
    if (t) {
      headers.Authorization = "Bearer " + t;
    }
    return headers;
  }

  async function authFetch(url, init) {
    const i = init || {};
    const headers = authHeaders(i.headers || {});
    return fetch(url, Object.assign({}, i, {
      headers,
      credentials: i.credentials === undefined ? "include" : i.credentials,
    }));
  }

  /** 将 Bearer / Cookie 中的 JWT 再写入 HttpOnly Cookie，便于后续整页导航。 */
  async function establishSessionFromStoredToken() {
    const t = getStoredAuthToken();
    if (!t) {
      return false;
    }
    try {
      const res = await fetch("/user/establish_session", {
        method: "POST",
        credentials: "include",
        headers: { Authorization: "Bearer " + t, "Content-Type": "application/json" },
      });
      return res.ok;
    } catch (e) {
      return false;
    }
  }

  /**
   * 发送邮箱验证码；若后端仍有 10 分钟内有效码且未 confirm_resend，会弹出二次确认后重发同一码。
   * @returns {{ cancelled: boolean, data?: object }}
   */
  async function requestVerificationCode(url, body, fetchFn) {
    const doFetch = fetchFn || fetch;
    const send = (confirmResend) =>
      doFetch(url, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({}, body, { confirm_resend: confirmResend })),
      }).then((res) => res.json().catch(() => ({})));

    let data = await send(false);
    if (data.status === "confirm_resend") {
      const msg = data.reason || "监测到您当前有一个有效的验证码可以直接填写。确认重发吗？";
      if (!global.confirm(msg)) {
        return { cancelled: true };
      }
      data = await send(true);
    }
    return { cancelled: false, data };
  }

  global.ClockTowerAuth = {
    AUTH_TOKEN_STORAGE_KEY,
    getStoredAuthToken,
    setStoredAuthToken,
    clearStoredAuthToken,
    authHeaders,
    authFetch,
    establishSessionFromStoredToken,
    requestVerificationCode,
  };
})(typeof window !== "undefined" ? window : globalThis);
