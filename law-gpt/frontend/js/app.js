/* Law GPT – Tra cứu thuốc | Infranixx
 * Logic frontend: trợ lý AI dạng nút bấm (thay cho thanh tìm kiếm), tờ thông tin thuốc,
 * danh mục và thống kê.
 * Chạy hoàn toàn tĩnh (không cần build) nên upload thẳng lên file manager của hosting được.
 */
(function () {
  "use strict";

  var CFG = window.LAWGPT_CONFIG || {};
  var DATA = window.LAWGPT_DATA || { meta: {}, groups: [], drugs: [] };

  // group: nhóm đang chọn; query: từ khóa người dùng gõ cho trợ lý (nếu có)
  var state = { group: null, query: "", selectedId: null, focusChoices: false };

  var $ = function (sel) { return document.querySelector(sel); };
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var isNarrow = function () { return window.matchMedia("(max-width: 1000px)").matches; };

  /* ---------- Tiện ích ---------- */

  function el(tag, opts, children) {
    opts = opts || {};
    var node = document.createElement(tag);
    if (opts.cls) node.className = opts.cls;
    if (opts.text != null) node.textContent = opts.text;
    if (opts.attrs) Object.keys(opts.attrs).forEach(function (k) { node.setAttribute(k, opts.attrs[k]); });
    if (opts.on) Object.keys(opts.on).forEach(function (k) { node.addEventListener(k, opts.on[k]); });
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  // Bỏ dấu tiếng Việt để gõ "giam dau" vẫn ra "Giảm đau".
  function normalize(s) {
    return String(s == null ? "" : s)
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/đ/g, "d")
      .trim();
  }

  function goTo(node) {
    node.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }

  function groupById(id) {
    for (var i = 0; i < DATA.groups.length; i++) if (DATA.groups[i].id === id) return DATA.groups[i];
    return null;
  }
  function groupName(id) { var g = groupById(id); return g ? g.name : ""; }
  function hueOf(groupId) { var g = groupById(groupId); return g && g.hue ? "var(--hue-" + g.hue + ")" : "var(--brand)"; }
  function applyHue(node, groupId) { node.style.setProperty("--hue", hueOf(groupId)); return node; }

  function drugById(id) {
    for (var i = 0; i < DATA.drugs.length; i++) if (DATA.drugs[i].id === id) return DATA.drugs[i];
    return null;
  }
  function drugsInGroup(id) { return DATA.drugs.filter(function (d) { return d.group === id; }); }

  function searchDrugs(query, groupId) {
    var terms = normalize(query).split(/\s+/).filter(Boolean);
    return DATA.drugs.filter(function (d) {
      if (groupId && d.group !== groupId) return false;
      if (!terms.length) return true;
      var hay = normalize([d.name, d.activeIngredient, d.form, d.manufacturer, groupName(d.group)].join(" "));
      return terms.every(function (t) { return hay.indexOf(t) !== -1; });
    });
  }

  /* ---------- Danh mục thuốc ---------- */

  var resultsEl = $("#results");
  var countEl = $("#result-count");
  var clearBtn = $("#clear-filter");

  function renderResults() {
    var list = searchDrugs(state.query, state.group);
    resultsEl.replaceChildren();

    var scope = state.group ? " trong nhóm " + groupName(state.group) : (state.query ? " khớp “" + state.query + "”" : "");
    countEl.textContent = list.length + " thuốc" + scope;
    clearBtn.hidden = !(state.group || state.query);

    if (!list.length) {
      resultsEl.appendChild(el("li", { cls: "empty", text: "Không có thuốc phù hợp. Bấm “Xem tất cả” hoặc chọn nhóm khác ở trợ lý." }));
      return;
    }
    list.forEach(function (d) {
      var btn = el("button", {
        cls: "row",
        attrs: { type: "button", "aria-pressed": String(d.id === state.selectedId) },
        on: { click: function () { selectDrug(d.id, true); } }
      }, [
        el("span", { cls: "row-name", text: d.name }),
        el("span", { cls: "row-active", text: d.activeIngredient }),
        el("span", { cls: "row-form", text: d.form }),
        applyHue(el("span", { cls: "tag", text: groupName(d.group) }), d.group)
      ]);
      applyHue(btn, d.group);
      resultsEl.appendChild(el("li", {}, [btn]));
    });
  }

  clearBtn.addEventListener("click", function () {
    state.group = null;
    state.query = "";
    renderResults();
  });

  /* ---------- Tờ thông tin thuốc ---------- */

  var detailEl = $("#detail");

  function fact(label, value, placeholder) {
    var dd = el("dd", { text: value || placeholder });
    if (!value) dd.className = "pending";
    return el("div", {}, [el("dt", { text: label }), dd]);
  }

  // d = null: tờ trống, cho người dùng thấy sẽ có những mục nào.
  function renderDetail(d) {
    detailEl.replaceChildren();
    detailEl.classList.toggle("is-empty", !d);
    detailEl.style.setProperty("--hue", d ? hueOf(d.group) : "var(--brand)");
    var blank = d ? "Chưa đồng bộ" : "–";

    var title = el("div", {}, [el("h3", { text: d ? d.name : "Chưa chọn thuốc" })]);
    if (d) {
      title.appendChild(applyHue(el("span", { cls: "tag", text: groupName(d.group) }), d.group));
    } else {
      title.appendChild(el("p", { cls: "leaflet-hint", text: "Chọn nhóm thuốc, rồi chọn tên thuốc ở trợ lý. Thông tin sẽ hiện ở đây." }));
    }
    var head = el("div", { cls: "leaflet-head" }, [title]);
    if (d) {
      head.appendChild(el("button", { cls: "link-btn", attrs: { type: "button" }, text: "Bỏ chọn", on: { click: closeDetail } }));
    }
    detailEl.appendChild(head);

    var factsList = [
      fact("Hoạt chất", d && d.activeIngredient, blank),
      fact("Hàm lượng", d && d.strength, blank),
      fact("Dạng bào chế", d && d.form, blank),
      fact("Nhà sản xuất", d && (d.country ? (d.manufacturer + " (" + d.country + ")") : d.manufacturer), blank),
      fact("Số đăng ký", d && d.registrationNo, blank)
    ];
    if (d && d.packaging) factsList.push(fact("Quy cách", d.packaging, blank));
    if (d && d.indications) factsList.push(fact("Chỉ định", d.indications, blank));
    if (d && d.dosage) factsList.push(fact("Liều dùng", d.dosage, blank));
    if (d && d.contraindications) factsList.push(fact("Chống chỉ định", d.contraindications, blank));

    detailEl.appendChild(el("dl", { cls: "facts" }, factsList));

    if (d) {
      var same = drugsInGroup(d.group).filter(function (x) { return x.id !== d.id; });
      if (same.length) {
        detailEl.appendChild(el("p", { cls: "leaflet-sub", text: "Thuốc cùng nhóm" }));
        var chips = el("div", { cls: "chips" });
        same.forEach(function (x) {
          chips.appendChild(applyHue(el("button", {
            cls: "cap cap-sm",
            attrs: { type: "button" },
            text: x.name,
            on: { click: function () { say("user", x.name); onDrug(x); } }
          }), x.group));
        });
        detailEl.appendChild(chips);
      }
    }

    detailEl.appendChild(el("p", {
      cls: "notice",
      text: "Thông tin chỉ mang tính tham khảo, không thay thế tư vấn của bác sĩ hoặc dược sĩ."
    }));
  }

  function closeDetail() {
    state.selectedId = null;
    renderDetail(null);
    renderResults();
  }

  function selectDrug(id, scroll) {
    var d = drugById(id);
    if (!d) return;
    state.selectedId = id;
    renderResults();
    renderDetail(d);
    if (scroll && isNarrow()) goTo(detailEl);
  }

  /* ---------- Thống kê ---------- */

  function countBy(list, keyFn) {
    var map = {};
    list.forEach(function (x) { var k = keyFn(x) || "Chưa rõ"; map[k] = (map[k] || 0) + 1; });
    return Object.keys(map).map(function (k) { return { name: k, n: map[k] }; })
      .sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name, "vi"); });
  }

  function table(caption, rows) {
    var tbody = el("tbody");
    rows.forEach(function (r) {
      tbody.appendChild(el("tr", {}, [el("th", { text: r.name, attrs: { scope: "row" } }), el("td", { text: String(r.n) })]));
    });
    return el("table", {}, [el("caption", { text: caption }), tbody]);
  }

  function renderStats() {
    var byGroup = DATA.groups.map(function (g) { return { name: g.name, n: drugsInGroup(g.id).length }; })
      .sort(function (a, b) { return b.n - a.n; });
    var byForm = countBy(DATA.drugs, function (d) { return d.form; });

    $("#stat-total").textContent = String(DATA.drugs.length);
    $("#stat-groups").textContent = String(DATA.groups.length);
    $("#stat-forms").textContent = String(byForm.length);

    var body = $("#table-view-body");
    body.replaceChildren(table("Số thuốc theo nhóm", byGroup), table("Số thuốc theo dạng bào chế", byForm));
  }

  function renderBadge() {
    var badge = $("#data-badge");
    var src = CFG.sourceName || "Cục Quản lý Dược – Bộ Y tế";
    var sample = !!(DATA.meta && DATA.meta.isSample);
    badge.classList.toggle("is-sample", sample);
    badge.textContent = sample
      ? "Dữ liệu thật từ " + src + " sẽ được nạp khi backend sẵn sàng."
      : "Nguồn dữ liệu: " + src + (DATA.meta && DATA.meta.updatedAt ? ", cập nhật " + DATA.meta.updatedAt : "") + ".";
  }

  /* ---------- Trợ lý AI (nút bấm thay cho thanh tìm kiếm) ---------- */

  var chatLog = $("#chat-log");
  var chatChoices = $("#chat-choices");
  var chatForm = $("#chat-form");
  var chatInput = $("#chat-input");

  function scrollChat() { chatLog.scrollTop = chatLog.scrollHeight; }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatMarkdown(text) {
    var safe = escapeHtml(text);
    return safe
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.*?)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  }

  function say(role, text, isEmergency) {
    var bubble = el("div", { cls: "bubble" });
    if (role === "bot") {
      bubble.innerHTML = formatMarkdown(text);
      if (isEmergency) bubble.classList.add("is-emergency");
    } else {
      bubble.textContent = text;
    }
    chatLog.appendChild(el("div", { cls: "msg msg-" + role }, [bubble]));
    scrollChat();
  }

  function botSay(text, delay, isEmergency) {
    return new Promise(function (resolve) {
      var dots = el("div", { cls: "msg msg-bot", attrs: { "aria-hidden": "true" } }, [
        el("div", { cls: "bubble typing" }, [el("i"), el("i"), el("i")])
      ]);
      chatLog.appendChild(dots);
      scrollChat();
      setTimeout(function () {
        dots.remove();
        say("bot", text, isEmergency);
        resolve();
      }, reduceMotion ? 0 : (delay == null ? 450 : delay));
    });
  }

  // items: [{ label, group (id nhóm để lấy màu), soft, action }]
  function setChoices(items) {
    chatChoices.replaceChildren();
    var first = null;
    items.forEach(function (it) {
      var btn = el("button", {
        cls: "cap" + (it.soft ? " cap-soft" : ""),
        attrs: { type: "button" },
        text: it.label,
        on: { click: function () { state.focusChoices = true; say("user", it.label); it.action(); } }
      });
      if (it.group) applyHue(btn, it.group);
      chatChoices.appendChild(btn);
      if (!first) first = btn;
    });
    // Giữ vị trí bàn phím: nút vừa bấm bị thay mới, nên chuyển focus sang nút đầu tiên.
    if (first && state.focusChoices) { first.focus({ preventScroll: true }); state.focusChoices = false; }
  }

  var otherGroup = function () {
    return { label: "Chọn nhóm khác", soft: true, action: function () { showGroups("Bạn muốn xem nhóm thuốc nào?"); } };
  };

  function groupChoices() {
    return DATA.groups.map(function (g) {
      return { label: g.name, group: g.id, action: function () { onGroup(g); } };
    });
  }

  function showGroups(message) {
    setChoices([]);
    return botSay(message).then(function () { setChoices(groupChoices()); });
  }

  function onGroup(g) {
    var list = drugsInGroup(g.id);
    state.group = g.id;
    state.query = "";
    state.selectedId = null;
    renderDetail(null);
    renderResults();
    setChoices([]);
    var text = list.length
      ? "Nhóm " + g.name + " có " + list.length + " thuốc trong dữ liệu. Bạn muốn xem thuốc nào?"
      : "Nhóm " + g.name + " chưa có thuốc trong dữ liệu.";
    botSay(text).then(function () {
      var items = list.map(function (d) {
        return { label: d.name, group: d.group, action: function () { onDrug(d); } };
      });
      items.push(otherGroup());
      setChoices(items);
    });
  }

  // Bấm nút thuốc = tra cứu luôn: tờ thông tin hiện ra và danh mục đánh dấu thuốc đó.
  function onDrug(d) {
    setChoices([]);
    state.group = d.group;
    state.query = "";
    selectDrug(d.id, true);
    botSay("Đây là thông tin của " + d.name + " (" + groupName(d.group) + "). Bạn muốn làm gì tiếp?").then(function () {
      setChoices([
        { label: "Xem thuốc cùng nhóm", group: d.group, action: function () { onGroup(groupById(d.group)); } },
        otherGroup(),
        { label: "Xem thống kê", soft: true, action: function () {
            goTo($("#thong-ke"));
            botSay("Mình đã cuộn tới phần thống kê cho bạn.").then(function () { setChoices([otherGroup()]); });
        } }
      ]);
    });
  }

  function askBackend(message) {
    var url = CFG.apiBase.replace(/\/$/, "") + "/api/chat";
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, group: state.group })
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  // Người dùng vẫn có thể nhắn tin: tìm trong dữ liệu có sẵn rồi trả lại nút để bấm.
  function handleLocal(text) {
    var q = normalize(text);

    var named = DATA.groups.filter(function (g) {
      var n = normalize(g.name);
      return q === n || q.indexOf(n) !== -1;
    })[0];
    if (named) return onGroup(named);

    var found = searchDrugs(text, null);
    if (found.length === 1) return onDrug(found[0]);
    if (found.length > 1) {
      state.group = null;
      state.query = text;
      state.selectedId = null;
      renderResults();
      return botSay("Mình thấy " + found.length + " thuốc phù hợp. Bạn muốn xem thuốc nào?").then(function () {
        var items = found.slice(0, 8).map(function (d) {
          return { label: d.name, group: d.group, action: function () { onDrug(d); } };
        });
        items.push(otherGroup());
        setChoices(items);
      });
    }

    var partial = q.length >= 3 && DATA.groups.filter(function (g) { return normalize(g.name).indexOf(q) !== -1; })[0];
    if (partial) return onGroup(partial);

    return showGroups("Mình chưa tìm thấy thuốc khớp với “" + text + "”. Bạn thử chọn một nhóm thuốc bên dưới nhé.");
  }

  function handleUserText(text) {
    say("user", text);
    setChoices([]);
    if (!CFG.apiBase) return handleLocal(text);
    askBackend(text).then(function (res) {
      var isEmergency = !!(res.ai_metadata && res.ai_metadata.is_emergency);
      return botSay(res.reply || "Mình đã nhận được yêu cầu.", null, isEmergency).then(function () {
        if (res.choices && res.choices.length) {
          setChoices(res.choices.map(function (c) {
            var q = c.query || c.label;
            var matchedDrug = DATA.drugs.filter(function (x) {
              return normalize(x.name) === normalize(q) || normalize(c.label).indexOf(normalize(x.name)) !== -1;
            })[0];
            return {
              label: c.label,
              group: matchedDrug ? matchedDrug.group : null,
              action: function () {
                if (q === "nhóm thuốc" || c.label === "Chọn nhóm khác") {
                  showGroups("Bạn muốn xem nhóm thuốc nào?");
                  return;
                }
                if (matchedDrug) {
                  onDrug(matchedDrug);
                  return;
                }
                var matchedGroup = DATA.groups.filter(function (x) {
                  return normalize(x.name) === normalize(q);
                })[0];
                if (matchedGroup) {
                  onGroup(matchedGroup);
                  return;
                }
                state.group = null;
                state.query = q;
                renderResults();
              }
            };
          }));
        }
      });
    }).catch(function (error) {
      console.error("Law GPT chat request failed:", error);
      botSay("Xin lỗi, hiện không thể kết nối với mô hình AI. Vui lòng kiểm tra cấu hình dịch vụ hoặc thử lại sau.");
    });
  }

  chatForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    handleUserText(text);
  });

  function startConversation() {
    state.group = null; state.query = ""; state.selectedId = null; state.focusChoices = false;
    chatLog.replaceChildren();
    setChoices([]);
    renderDetail(null);
    renderResults();
    botSay("Xin chào! Mình là trợ lý Law GPT của Infranixx. Bạn chỉ cần bấm nút để tra cứu thuốc, không cần gõ.", 300)
      .then(function () { return showGroups("Bạn đang cần tìm thuốc thuộc nhóm nào?"); });
  }

  $("#restart").addEventListener("click", startConversation);

  /* ---------- Khởi động ---------- */

  function init() {
    renderBadge();
    renderStats();
    startConversation();
  }

  // Nạp dữ liệu thật từ backend nếu đã cấu hình, nếu không dùng dữ liệu mẫu.
  if (CFG.apiBase) {
    fetch(CFG.apiBase.replace(/\/$/, "") + "/api/drugs")
      .then(function (res) { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function (json) { DATA = json; })
      .catch(function () { /* giữ dữ liệu mẫu */ })
      .then(init);
  } else {
    init();
  }
})();
