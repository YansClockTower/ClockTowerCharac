/**
 * 共用浮窗。静态弹窗用 AppModal.bind / AppModal.open；
 * 临时弹窗用 AppModal.create({ title, html, wide, actions })。
 */
(function (global) {
  function anyOpen() {
    return document.querySelector(".app-modal:not([hidden])");
  }

  function syncBody() {
    document.body.classList.toggle("app-modal-open", !!anyOpen());
  }

  function close(modal) {
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    syncBody();
    modal.dispatchEvent(new CustomEvent("app-modal-close"));
  }

  function bind(modal) {
    if (!modal) return null;
    if (modal.dataset.appModalBound === "1") {
      return modal._appModalApi;
    }
    modal.dataset.appModalBound = "1";
    modal.addEventListener("click", function (e) {
      if (e.target.closest("[data-app-modal-close]")) close(modal);
    });
    const api = {
      el: modal,
      open: function () {
        modal.hidden = false;
        syncBody();
      },
      close: function () {
        close(modal);
      },
      destroy: function () {
        close(modal);
        modal.remove();
      },
    };
    modal._appModalApi = api;
    return api;
  }

  function open(modal) {
    const api = bind(modal);
    if (api) api.open();
    return api;
  }

  function create(options) {
    const opts = options || {};
    const modal = document.createElement("div");
    modal.className = "app-modal" + (opts.wide ? " app-modal--wide" : "");
    modal.hidden = true;
    const titleId = "app-modal-title-" + Math.random().toString(36).slice(2, 8);
    const actions = opts.actions || [];
    const actionHtml = actions.map(function (action, index) {
      const cls = action.primary ? "app-modal-btn app-modal-btn--primary" : "app-modal-btn";
      return '<button type="button" class="' + cls + '" data-app-modal-action="' + index + '"></button>';
    }).join("");
    modal.innerHTML =
      '<div class="app-modal-backdrop" data-app-modal-close></div>' +
      '<div class="app-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="' + titleId + '">' +
        '<div class="app-modal-header">' +
          '<h3 id="' + titleId + '"></h3>' +
          '<button type="button" class="app-modal-close" data-app-modal-close aria-label="关闭">×</button>' +
        "</div>" +
        '<div class="app-modal-body"></div>' +
        (actionHtml ? '<div class="app-modal-actions">' + actionHtml + "</div>" : "") +
      "</div>";
    modal.querySelector("h3").textContent = opts.title || "";
    const body = modal.querySelector(".app-modal-body");
    if (typeof opts.html === "string") body.innerHTML = opts.html;
    document.body.appendChild(modal);
    const api = bind(modal);
    api.body = body;
    actions.forEach(function (action, index) {
      const button = modal.querySelector('[data-app-modal-action="' + index + '"]');
      button.textContent = action.label || "";
      button.addEventListener("click", function () {
        if (action.onClick) action.onClick(api);
      });
    });
    return api;
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    const openModals = document.querySelectorAll(".app-modal:not([hidden])");
    if (!openModals.length) return;
    close(openModals[openModals.length - 1]);
  });

  global.AppModal = {
    bind: bind,
    open: open,
    close: close,
    create: create,
  };
})(window);
