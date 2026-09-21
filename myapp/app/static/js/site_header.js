(function (global) {
  const link = document.getElementById("siteHeaderMessages");
  if (link) {
    const url = link.getAttribute("data-unread-url");
    async function refreshUnread() {
      try {
        const res = global.ClockTowerAuth
          ? await global.ClockTowerAuth.authFetch(url)
          : await fetch(url, { credentials: "include" });
        const data = await res.json().catch(function () { return {}; });
        link.classList.toggle("is-unread", !!data.unread);
      } catch (e) {}
    }
    refreshUnread();
    global.setInterval(refreshUnread, 20000);
  }

  global.logoutUser = async function logoutUser(event) {
    if (event) event.preventDefault();
    if (!global.confirm("确定要登出吗？")) return;
    try {
      await (global.ClockTowerAuth
        ? global.ClockTowerAuth.authFetch("/user/logout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          })
        : fetch("/user/logout", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
          }));
    } catch (e) {}
    if (global.ClockTowerAuth) {
      global.ClockTowerAuth.clearStoredAuthToken();
    }
    global.location.href = "/user/login";
  };
})(window);
