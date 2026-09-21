/**
 * 发布活动前若未留微信号，用共用浮窗建议填写；活动卡片上查看组局者微信。
 */
(function (global) {
  const BLANK = { "": true, "保密": true, "未填写": true, "无": true, "-": true, "—": true };
  const ADMIN_WECHAT = "YJQ2364728692";

  function isBlank(value) {
    return !!BLANK[(value || "").trim()];
  }

  async function currentContact() {
    if (!global.ClockTowerAuth) return null;
    try {
      const res = await global.ClockTowerAuth.authFetch("/user/me", {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) return null;
      const data = await res.json();
      return (data && data.contact_info) || "";
    } catch (e) {
      return null;
    }
  }

  async function saveContact(value) {
    const res = await global.ClockTowerAuth.authFetch("/user/profile_update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contact_info: value }),
    });
    const data = await res.json().catch(function () { return {}; });
    if (!res.ok || !data || data.status !== "success") {
      throw new Error((data && data.reason) || "保存失败");
    }
  }

  function promptForWechat() {
    return new Promise(function (resolve) {
      let settled = false;
      function finish(ok) {
        if (settled) return;
        settled = true;
        resolve(ok);
      }
      const modal = global.AppModal.create({
        title: "建议先填写微信号",
        html:
          "<p>发布后，其他成员可以在活动列表里点开你名字旁的微信图标联系你。</p>" +
          '<label class="app-modal-label" for="quick-wechat">微信号</label>' +
          '<input id="quick-wechat" class="app-modal-input" type="text" maxlength="128" autocomplete="off" placeholder="例如：YJQ2364728692">' +
          '<p class="app-modal-error" hidden></p>',
        actions: [
          {
            label: "仍要发布",
            onClick: function (api) {
              finish(true);
              api.destroy();
            },
          },
          {
            label: "保存并发布",
            primary: true,
            onClick: async function (api) {
              const input = api.body.querySelector("#quick-wechat");
              const err = api.body.querySelector(".app-modal-error");
              const value = (input.value || "").trim();
              if (isBlank(value)) {
                err.hidden = false;
                err.textContent = "请填写有效微信号，或选择「仍要发布」。";
                return;
              }
              try {
                await saveContact(value);
                finish(true);
                api.destroy();
              } catch (e) {
                err.hidden = false;
                err.textContent = e.message || "保存失败";
              }
            },
          },
        ],
      });
      modal.el.addEventListener("app-modal-close", function () {
        finish(false);
      });
      modal.open();
      const input = modal.body.querySelector("#quick-wechat");
      if (input) input.focus();
    });
  }

  function showOrganizerWechat(name, wechat, chatUrl) {
    const who = name || "组局者";
    let html;
    if (wechat) {
      html = '<p class="organizer-wechat-line"></p><p class="organizer-wechat-id"></p>';
    } else {
      html = "<p>组局者未留微信号。如果有问题，可以联系管理员（" + ADMIN_WECHAT + "）。</p>";
    }
    const modal = global.AppModal.create({
      title: "组局者微信号",
      html: html,
    });
    if (wechat) {
      const line = modal.body.querySelector(".organizer-wechat-line");
      line.textContent = "组局者「" + who + "」的微信号：";
      modal.body.querySelector(".organizer-wechat-id").textContent = wechat;
    }
    if (chatUrl) {
      const jump = document.createElement("p");
      jump.className = "organizer-chat-jump";
      const link = document.createElement("a");
      link.className = "base-btn join-btn";
      link.href = chatUrl;
      link.textContent = "进入聊天室";
      jump.appendChild(link);
      modal.body.appendChild(jump);
    }
    modal.open();
  }

  document.addEventListener("submit", async function (e) {
    const form = e.target;
    if (!form || !form.hasAttribute("data-require-wechat")) return;
    if (form.dataset.wechatOk === "1") return;
    if (!global.AppModal) return;
    e.preventDefault();
    const contact = await currentContact();
    const ok = contact === null || !isBlank(contact) ? true : await promptForWechat();
    if (!ok) return;
    form.dataset.wechatOk = "1";
    setTimeout(function () {
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    }, 0);
  }, true);

  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-organizer-wechat]");
    if (!btn || !global.AppModal) return;
    e.preventDefault();
    showOrganizerWechat(
      btn.getAttribute("data-name") || "",
      (btn.getAttribute("data-wechat") || "").trim(),
      (btn.getAttribute("data-chat-url") || "").trim()
    );
  });
})(window);
