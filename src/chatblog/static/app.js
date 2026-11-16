/* Chatblog Studio — vanilla JS, no build step. */
(() => {
  "use strict";

  const state = {
    token: null,
    settings: null,
    sources: null,
    entries: [],
    selected: new Set(),
    filters: { provider: "all", status: "all", tag: "", q: "", sort: "updated_desc" },
    jobId: null,
    pollTimer: null,
    busy: false,
  };

  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json" };
    if (state.token) headers["X-Studio-Token"] = state.token;
    const response = await fetch(path, {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = { error: "回應不是 JSON" };
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  function toast(message, isError = false) {
    const node = $("toast");
    node.textContent = message;
    node.classList.toggle("error", isError);
    node.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { node.hidden = true; }, isError ? 6000 : 3200);
  }

  function fmtDate(entry) {
    const raw = entry.updated_at || entry.created_at;
    if (!raw) return "—";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw.slice(0, 10);
    const pad = (n) => String(n).padStart(2, "0");
    const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    return date.getHours() || date.getMinutes() ? `${day} ${time}` : day;
  }

  function providerLabel(provider) {
    return provider === "gemini" ? "G" : "W";
  }

  // ---------------------------------------------------------------- render
  function renderSources() {
    const host = $("sources");
    const sources = state.sources || {};
    const owui = sources.openwebui || {};
    const gemini = sources.gemini || {};
    const geminiState = gemini.state || {};
    const parts = [];

    parts.push(
      `<span class="chip-source ${owui.ok === false ? "bad" : "ok"}">` +
        `<span class="dot"></span><strong>OpenWebUI</strong>` +
        `<span>${esc(owui.count || 0)} 個${owui.detail ? " · " + esc(String(owui.detail).slice(0, 40)) : ""}</span>` +
      `</span>`
    );

    let geminiDetail = "未登入";
    let geminiClass = "bad";
    let geminiTitle = String(geminiState.detail || "");
    if (geminiState.ok && geminiState.count) {
      geminiDetail = `${geminiState.count} 個`;
      geminiClass = "ok";
    } else if (gemini.running) {
      geminiDetail = "Chrome 開著";
      geminiClass = "";
    }
    parts.push(
      `<span class="chip-source ${geminiClass}" title="${esc(geminiTitle)}">` +
        `<span class="dot"></span><strong>Gemini</strong><span>${esc(geminiDetail)}</span>` +
      `</span>`
    );

    host.innerHTML = parts.join("");
  }

  function compactMeta(entry) {
    const bits = [];
    if (entry.models && entry.models.length) bits.push(entry.models.join("、"));
    if (entry.message_count) bits.push(`${entry.message_count} 訊息`);
    if (entry.group) bits.push(entry.group);
    if (entry.classification && entry.classification.provider === "rules") bits.push("規則分類");
    if (entry.needs_classification && (entry.tags || []).length) bits.push("待補分類");
    return bits.join(" · ");
  }

  function tagChips(entry) {
    const tags = entry.tags || [];
    if (!tags.length) {
      return '<span class="tag untagged">未分類</span>';
    }
    // Cap the visible tags so every row keeps one line; the rest live in the
    // "+N" hover and in the tag filter.
    const shown = tags.slice(0, 5);
    const hidden = tags.slice(5);
    const html = shown
      .map(
        (tag) =>
          `<span class="tag ${esc(tag.dim || "")}" data-tag="${esc(tag.name)}" ` +
          `title="${esc(tag.dim)} · 信心 ${(tag.confidence * 100).toFixed(0)}%">${esc(tag.name)}</span>`
      )
      .join("");
    if (!hidden.length) return html;
    return (
      html +
      `<span class="tag more" title="${esc(hidden.map((tag) => tag.name).join(" · "))}">+${hidden.length}</span>`
    );
  }

  function statusPill(entry) {
    if (entry.status === "published") {
      return `<span class="status-pill published" title="${esc(entry.post_path)}">已上傳</span>`;
    }
    if (entry.status === "stale") {
      return `<span class="status-pill stale" title="${esc(entry.post_path)}">有更新</span>`;
    }
    return '<span class="status-pill new">未上傳</span>';
  }

  function sortEntries(rows) {
    const mode = state.filters.sort;
    const moment = (entry) => entry.updated_at || entry.created_at || "";
    const copy = rows.slice();
    if (mode === "updated_asc") {
      copy.sort((a, b) => (moment(a) < moment(b) ? -1 : moment(a) > moment(b) ? 1 : 0));
    } else if (mode === "title") {
      copy.sort((a, b) => a.title.localeCompare(b.title, "zh-Hant"));
    } else {
      copy.sort((a, b) => (moment(a) > moment(b) ? -1 : moment(a) < moment(b) ? 1 : 0));
    }
    return copy;
  }

  function visibleEntries() {
    const filters = state.filters;
    const query = filters.q.trim().toLowerCase();
    return sortEntries(
      state.entries.filter((entry) => {
        if (filters.provider !== "all" && entry.provider !== filters.provider) return false;
        if (filters.status !== "all" && entry.status !== filters.status) return false;
        if (filters.tag && !(entry.tags || []).some((tag) => tag.name === filters.tag)) return false;
        if (query) {
          const haystack = `${entry.title} ${(entry.tags || []).map((tag) => tag.name).join(" ")}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      })
    );
  }

  function renderRows() {
    const rows = visibleEntries();
    const host = $("rows");
    $("empty").hidden = rows.length > 0 || state.entries.length > 0;
    if (!rows.length) {
      host.innerHTML = state.entries.length
        ? '<div class="empty"><p>沒有符合條件的對話。</p></div>'
        : '<div class="empty"><p>還沒有對話。</p><p class="muted">按「重新整理」讀取 OpenWebUI 與 Gemini。</p></div>';
      updateBar(rows);
      return;
    }

    host.innerHTML = rows
      .map((entry) => {
        const selected = state.selected.has(entry.key) ? " selected" : "";
        const published = entry.status === "published" ? " published" : "";
        const approx = entry.approximate_date ? '<span class="approx" title="Gemini 側邊欄只提供大致日期">~</span>' : "";
        return (
          `<div class="row${selected}${published}" data-key="${esc(entry.key)}">` +
          `<label class="check"><input type="checkbox" ${selected ? "checked" : ""}></label>` +
          `<div class="cell-title">` +
            `<div class="title-line">` +
              `<span class="provider-badge ${esc(entry.provider)}" title="${esc(entry.provider)}">${providerLabel(entry.provider)}</span>` +
              `<button class="title-text" data-url="${esc(entry.url)}" title="${esc(entry.url)}">${esc(entry.title)}</button>` +
              `<button class="open-ext" data-url="${esc(entry.url)}" title="用外部瀏覽器開啟">↗</button>` +
            `</div>` +
            `<div class="meta" title="${esc((entry.classification || {}).error || "")}">${esc(compactMeta(entry))}</div>` +
          `</div>` +
          `<div class="cell-date">${approx}${esc(fmtDate(entry))}</div>` +
          `<div class="cell-tags">${tagChips(entry)}</div>` +
          `<div class="cell-status">${statusPill(entry)}</div>` +
        `</div>`
        );
      })
      .join("");
    updateBar(rows);
  }

  function renderTagFilter() {
    const counts = new Map();
    for (const entry of state.entries) {
      for (const tag of entry.tags || []) {
        counts.set(tag.name, (counts.get(tag.name) || 0) + 1);
      }
    }
    const select = $("tagFilter");
    const current = state.filters.tag;
    const options = [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hant"))
      .map(([name, count]) => `<option value="${esc(name)}">${esc(name)} (${count})</option>`)
      .join("");
    select.innerHTML = `<option value="">所有標籤</option>${options}`;
    select.value = current && counts.has(current) ? current : "";
    state.filters.tag = select.value;
  }

  function updateBar(rows) {
    const list = rows || visibleEntries();
    $("selectedCount").textContent = String(state.selected.size);
    $("visibleCount").textContent = `／顯示 ${list.length} 個（共 ${state.entries.length}）`;
    $("publishBtn").disabled = state.selected.size === 0;
    $("classifyBtn").disabled = state.busy;
    const all = list.length > 0 && list.every((entry) => state.selected.has(entry.key));
    $("selectAll").checked = all;
    $("selectAll").indeterminate = !all && list.some((entry) => state.selected.has(entry.key));
  }

  // ---------------------------------------------------------------- data
  async function loadChats() {
    const payload = await api("/api/chats");
    state.entries = payload.entries || [];
    state.sources = payload.sources || state.sources;
    const known = new Set(state.entries.map((entry) => entry.key));
    for (const key of [...state.selected]) {
      if (!known.has(key)) state.selected.delete(key);
    }
    renderSources();
    renderTagFilter();
    renderRows();
  }

  async function bootstrap() {
    const payload = await fetch("/api/bootstrap").then((response) => response.json());
    state.token = payload.token;
    state.settings = payload.settings;
    state.sources = payload.sources;
    fillSettings(payload.settings);
    renderSources();
    await loadChats();
  }

  // ---------------------------------------------------------------- jobs
  function jobTitle(kind) {
    return { refresh: "讀取對話列表", classify: "自動分類", publish: "生成文章" }[kind] || kind;
  }

  function startPolling(job) {
    state.jobId = job.id;
    state.busy = true;
    updateBar();
    $("jobCard").hidden = false;
    $("jobTitle").textContent = `${jobTitle(job.kind)}…`;
    $("jobBar").style.width = "0%";
    $("jobMeta").textContent = `0 / ${job.total}`;
    $("jobItems").innerHTML = "";
    $("jobCancel").hidden = false;
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollJob, 900);
    pollJob();
  }

  async function pollJob() {
    if (!state.jobId) return;
    let job;
    try {
      job = await api(`/api/jobs/${state.jobId}`);
    } catch (error) {
      clearInterval(state.pollTimer);
      return;
    }
    const percent = job.total ? Math.round((job.done / job.total) * 100) : 0;
    $("jobBar").style.width = `${percent}%`;
    $("jobMeta").textContent =
      `${job.done} / ${job.total}` + (job.token_usage ? ` · ${job.token_usage} tokens` : "") +
      (job.message ? ` · ${job.message}` : "");
    renderJobItems(job);

    if (job.status !== "running") {
      clearInterval(state.pollTimer);
      state.busy = false;
      $("jobCancel").hidden = true;
      $("jobTitle").textContent = job.status === "done" ? `${jobTitle(job.kind)}完成` : `${jobTitle(job.kind)}中止`;
      $("jobBar").style.width = "100%";
      await loadChats().catch(() => {});
      updateBar();
      if (job.kind === "publish") {
        const failed = (job.items || []).filter((item) => !item.ok);
        toast(failed.length ? `${job.items.length - failed.length} 篇完成，${failed.length} 篇失敗` : `已生成 ${job.items.length} 篇文章`, failed.length > 0);
      } else if (job.kind === "classify") {
        const pending = (job.items || []).filter((item) => !item.ok).length;
        toast(`${(job.items || []).length - pending} 個分類完成${pending ? `，${pending} 個待補分類` : ""}`, pending > 0);
      }
    }
  }

  function renderJobItems(job) {
    const host = $("jobItems");
    host.innerHTML = (job.items || [])
      .slice(-40)
      .map((item) => {
        if (item.ok) {
          const detail = item.post_path ? `<span class="path">${esc(item.post_path)}</span>` : (item.tags ? `<span class="path">${esc((item.tags || []).join(" · "))}</span>` : "");
          return `<div class="job-item"><span class="ok">✓</span><span>${esc(item.title || item.key)}</span>${detail}</div>`;
        }
        return `<div class="job-item"><span class="bad">✗</span><span>${esc(item.title || item.key)}</span><span class="path">${esc(item.error || "")}</span></div>`;
      })
      .join("");
  }

  async function runJob(path, body, kind) {
    if (state.busy) {
      toast("有另一個工作進行中，請等它完成。", true);
      return;
    }
    try {
      const job = await api(path, { method: "POST", body });
      startPolling(job);
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ---------------------------------------------------------------- links
  async function openLink(url) {
    if (!url) return;
    try {
      const result = await api("/api/open", { method: "POST", body: { url } });
      toast(`已用 ${result.browser} 開啟`);
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ---------------------------------------------------------------- settings
  function fillSettings(settings) {
    if (!settings) return;
    const form = $("settingsForm");
    const isGemini = settings.classifier_provider === "gemini";
    $("classifierName").textContent = isGemini ? "Google Gemini Decision 1" : "OpenJev / System One";
    $("classifierKeyStatus").textContent = settings.classifier_key_set ? "金鑰已設定" : "尚未設定金鑰";
    $("classifierKeyStatus").classList.toggle("configured", !!settings.classifier_key_set);
    $("geminiDecisionSettings").hidden = !isGemini;
    $("geminiDecisionSettings").querySelector(".classifier-note").textContent = settings.classifier_key_set
      ? "金鑰已從本機 .env 載入；模型與網址也由此設定。"
      : "請在本機 .env 設定 GEMINI_API_KEY 後重新啟動。";
    $("openjevSettings").hidden = isGemini;
    $("testClassifier").textContent = isGemini ? "測試 Gemini 連線" : "測試 OpenJev 連線";
    $("classifierStatus").textContent = "";
    form.classifier_model.value = settings.classifier_model || "";
    form.classifier_base_url.value = settings.classifier_base_url || "";
    form.openjev_base_url.value = settings.openjev_base_url || "";
    form.openjev_model.value = settings.openjev_model || "";
    form.gemini_profile.value = settings.gemini_profile || "";
    form.gemini_port.value = settings.gemini_port || 9333;
    form.gemini_headless.checked = settings.gemini_headless !== false;
    form.open_browser.value = settings.open_browser || "auto";
    form.owui_base_url.value = settings.owui_base_url || "";
    $("keyHint").textContent = settings.openjev_key_set ? `（已設定 ${settings.openjev_key_hint}）` : "（未設定）";
    $("pathsHint").textContent = `索引：${settings.ledger_path} · 資料夾：${settings.data_dir}`;
  }

  async function saveSettings() {
    const form = $("settingsForm");
    const payload = {
      gemini_port: Number(form.gemini_port.value) || 9333,
      gemini_headless: form.gemini_headless.checked,
      open_browser: form.open_browser.value,
      owui_base_url: form.owui_base_url.value.trim(),
    };
    if (state.settings.classifier_provider !== "gemini") {
      payload.openjev_base_url = form.openjev_base_url.value.trim();
      payload.openjev_model = form.openjev_model.value.trim();
      if (form.openjev_api_key.value.trim()) payload.openjev_api_key = form.openjev_api_key.value.trim();
    }
    try {
      const result = await api("/api/settings", { method: "POST", body: payload });
      state.settings = result.settings;
      fillSettings(result.settings);
      form.openjev_api_key.value = "";
      $("settingsDialog").close();
      toast("設定已儲存");
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function testClassifier() {
    $("classifierStatus").textContent = "測試中…";
    $("testClassifier").disabled = true;
    try {
      const result = await api("/api/openjev/test", { method: "POST", body: {} });
      $("classifierStatus").textContent = result.ok
        ? `連線成功 · ${(result.info.models || []).slice(0, 4).join(", ") || result.info.model || ""}`
        : `失敗：${result.error}`;
    } catch (error) {
      $("classifierStatus").textContent = `失敗：${error.message}`;
    } finally {
      $("testClassifier").disabled = false;
    }
  }

  async function geminiLogin() {
    try {
      const result = await api("/api/gemini/login", { method: "POST", body: {} });
      toast(result.message || "已開啟 Chrome");
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function geminiCheck() {
    $("geminiStatus").textContent = "檢查中…";
    try {
      const result = await api("/api/gemini/check", { method: "POST", body: {} });
      if (result.logged_in) {
        $("geminiStatus").textContent = `已登入 · 看到 ${result.count} 個對話`;
      } else {
        $("geminiStatus").textContent = result.error ? `失敗：${result.error}` : "未登入";
      }
    } catch (error) {
      $("geminiStatus").textContent = `失敗：${error.message}`;
    }
  }

  // ---------------------------------------------------------------- publish
  function openPublishDialog() {
    if (!state.selected.size) return;
    $("publishSummary").textContent = `已選 ${state.selected.size} 個對話，會寫入 source/_posts 並更新索引。`;
    $("publishDialog").showModal();
  }

  async function confirmPublish() {
    $("publishDialog").close();
    await runJob("/api/publish", {
      keys: [...state.selected],
      private: $("optPrivate").checked,
      force_assets: $("optForce").checked,
      date: $("optDate").value,
    });
    state.selected.clear();
    renderRows();
  }

  // ---------------------------------------------------------------- events
  function wire() {
    $("refreshBtn").addEventListener("click", () => runJob("/api/refresh", { providers: ["openwebui", "gemini"] }));
    $("settingsBtn").addEventListener("click", () => $("settingsDialog").showModal());
    $("selectAllVisible").addEventListener("click", () => {
      for (const entry of visibleEntries()) state.selected.add(entry.key);
      renderRows();
    });
    $("clearSelection").addEventListener("click", () => {
      state.selected.clear();
      renderRows();
    });
    $("selectAll").addEventListener("change", (event) => {
      const rows = visibleEntries();
      if (event.target.checked) rows.forEach((entry) => state.selected.add(entry.key));
      else rows.forEach((entry) => state.selected.delete(entry.key));
      renderRows();
    });

    $("classifyBtn").addEventListener("click", async () => {
      if (state.selected.size) {
        await runJob("/api/classify", { keys: [...state.selected] });
      } else {
        const pending = state.entries.filter((entry) => entry.needs_classification).length;
        if (!pending) {
          toast("所有對話都已分類。");
          return;
        }
        if (confirm(`要分類所有 ${pending} 個未分類或待補分類的對話嗎？（會逐個讀取內容，需時較長）`)) {
          await runJob("/api/classify", { all: true });
        }
      }
    });

    $("publishBtn").addEventListener("click", openPublishDialog);
    $("publishCancel").addEventListener("click", () => $("publishDialog").close());
    $("publishConfirm").addEventListener("click", confirmPublish);

    $("jobClose").addEventListener("click", () => { $("jobCard").hidden = true; });
    $("jobCancel").addEventListener("click", async () => {
      if (!state.jobId) return;
      try { await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST", body: {} }); } catch (error) { /* ignore */ }
    });

    $("settingsCancel").addEventListener("click", () => $("settingsDialog").close());
    $("settingsSave").addEventListener("click", saveSettings);
    $("testClassifier").addEventListener("click", testClassifier);
    $("geminiLogin").addEventListener("click", geminiLogin);
    $("geminiCheck").addEventListener("click", geminiCheck);

    $("search").addEventListener("input", (event) => {
      state.filters.q = event.target.value;
      renderRows();
    });
    $("sortSelect").addEventListener("change", (event) => {
      state.filters.sort = event.target.value;
      renderRows();
    });
    $("tagFilter").addEventListener("change", (event) => {
      state.filters.tag = event.target.value;
      renderRows();
    });

    for (const [id, key] of [["providerFilter", "provider"], ["statusFilter", "status"]]) {
      $(id).addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button) return;
        for (const child of $(id).querySelectorAll("button")) child.classList.toggle("active", child === button);
        state.filters[key] = button.dataset.value;
        renderRows();
      });
    }

    $("rows").addEventListener("click", (event) => {
      const tag = event.target.closest("[data-tag]");
      if (tag) {
        state.filters.tag = tag.dataset.tag;
        $("tagFilter").value = tag.dataset.tag;
        renderRows();
        return;
      }
      const link = event.target.closest("[data-url]");
      if (link) {
        event.preventDefault();
        openLink(link.dataset.url);
        return;
      }
      const row = event.target.closest(".row");
      if (!row) return;
      if (event.target.matches("input[type=checkbox]")) return;
      const key = row.dataset.key;
      if (state.selected.has(key)) state.selected.delete(key);
      else state.selected.add(key);
      row.classList.toggle("selected", state.selected.has(key));
      row.querySelector("input[type=checkbox]").checked = state.selected.has(key);
      updateBar();
    });

    $("rows").addEventListener("change", (event) => {
      if (!event.target.matches("input[type=checkbox]")) return;
      const row = event.target.closest(".row");
      const key = row.dataset.key;
      if (event.target.checked) state.selected.add(key);
      else state.selected.delete(key);
      row.classList.toggle("selected", event.target.checked);
      updateBar();
    });

    // Escape closes dialogs natively; open the settings dialog with "?".
    document.addEventListener("keydown", (event) => {
      if (event.key === "?" && !event.target.matches("input, textarea, select")) {
        $("settingsDialog").showModal();
      }
    });
  }

  wire();
  bootstrap().catch((error) => {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div class="toast error">載入失敗：${esc(error.message)}</div>`
    );
  });
})();
