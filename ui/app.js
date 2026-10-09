const state = { drawings: [], selected: null, view: "preview", connectionOk: false, job: null };

const byId = (id) => document.getElementById(id);
const gallery = byId("gallery");
const preview = byId("art-preview");
const safetyConfirm = byId("safety-confirm");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || body.message || "请求失败");
  return body;
}

function selectedDrawing() {
  return state.drawings.find((drawing) => drawing.id === state.selected);
}

function updateActions() {
  const job = state.job;
  const active = Boolean(job?.active);
  const checkpoint = job?.states?.[state.selected];
  const status = checkpoint?.status;
  const ready = Boolean(state.selected && state.connectionOk && safetyConfirm.checked && !active);
  byId("draw-button").disabled = !(ready && !status);
  byId("stop-button").disabled = !active || Boolean(job?.stop_pending);
  byId("resume-button").disabled = !(ready && status === "paused");
  byId("restart-button").disabled = !(ready && ["paused", "complete"].includes(status));
}

function renderSelection() {
  const drawing = selectedDrawing();
  document.querySelectorAll(".art-card").forEach((card) => card.classList.toggle("selected", card.dataset.id === state.selected));
  if (!drawing) return;
  byId("selected-title").textContent = drawing.title;
  byId("selected-description").textContent = drawing.subtitle;
  preview.src = `/${drawing[state.view]}?v=${encodeURIComponent(drawing.id)}`;
  preview.alt = `${drawing.title}${state.view === "preview" ? "轨迹" : "参考线稿"}`;
  updateActions();
}

function renderGallery() {
  gallery.replaceChildren(...state.drawings.map((drawing) => {
    const button = document.createElement("button");
    button.className = "art-card";
    button.dataset.id = drawing.id;
    button.innerHTML = `<img src="/${drawing.preview}" alt="${drawing.title} 轨迹预览"><span>${drawing.title}</span><small>${drawing.subtitle}</small>`;
    button.addEventListener("click", () => { state.selected = drawing.id; renderSelection(); });
    return button;
  }));
}

function setConnection(result) {
  state.connectionOk = Boolean(result.available);
  byId("status-dot").classList.toggle("ok", state.connectionOk);
  byId("status-title").textContent = state.connectionOk ? "连接状态正常" : "连接未就绪";
  byId("status-detail").textContent = state.connectionOk
    ? `${result.can} · 已获得实时关节反馈`
    : (result.message || result.report || "请检查 Windows CAN 适配器、机械臂供电和急停状态。");
  updateActions();
}

async function refreshConnection() {
  const button = byId("status-button");
  button.disabled = true;
  button.textContent = "检查中…";
  try { setConnection(await api("/api/status")); }
  catch (error) { setConnection({ available: false, message: error.message }); }
  finally { button.disabled = false; button.textContent = "检查连接"; }
}

async function pollJob() {
  try {
    const job = await api("/api/job");
    state.job = job;
    const drawingId = job.active ? job.drawing_id : state.selected;
    const checkpoint = job.states?.[drawingId];
    const status = checkpoint?.status;
    const label = job.stop_pending ? "停止中" : job.active ? "作画中"
      : status === "paused" ? "已停止" : status === "complete" ? "已完成"
      : status === "stopped" ? "执行失败" : status === "invalid" ? "断点异常"
      : ["running", "interrupted"].includes(status) ? "状态未确认" : "空闲";
    byId("job-badge").textContent = label;
    byId("job-badge").classList.toggle("busy", job.active);
    const progress = checkpoint?.total != null
      ? `已完成 ${checkpoint.completed ?? 0}/${checkpoint.total} 笔；${checkpoint.active_command || checkpoint.phase || ""}`
      : "";
    const log = job.log?.length ? job.log.join("\n") : "等待执行器输出。";
    byId("job-log").textContent = [progress, checkpoint?.detail, log].filter(Boolean).join("\n\n");
    updateActions();
  } catch (error) { byId("job-log").textContent = `无法读取执行状态：${error.message}`; }
}

async function performMotion(endpoint, verb) {
  const drawing = selectedDrawing();
  if (!drawing) return;
  const warning = endpoint === "/api/restart"
    ? `确认从头重画《${drawing.title}》？请先换新纸，或确认允许覆盖现有笔迹。`
    : `确认${verb}《${drawing.title}》？`;
  if (!confirm(warning)) return;
  const button = endpoint === "/api/draw" ? byId("draw-button")
    : endpoint === "/api/resume" ? byId("resume-button") : byId("restart-button");
  button.disabled = true;
  try {
    const result = await api(endpoint, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ drawing_id: drawing.id, confirmed: safetyConfirm.checked }) });
    byId("job-log").textContent = result.message;
    await pollJob();
  } catch (error) { byId("job-log").textContent = `未启动：${error.message}`; updateActions(); }
}

document.querySelectorAll(".view-button").forEach((button) => button.addEventListener("click", () => {
  state.view = button.dataset.view;
  document.querySelectorAll(".view-button").forEach((item) => item.classList.toggle("active", item === button));
  renderSelection();
}));
safetyConfirm.addEventListener("change", updateActions);
byId("status-button").addEventListener("click", refreshConnection);
byId("draw-button").addEventListener("click", () => performMotion("/api/draw", "开始绘制"));
byId("resume-button").addEventListener("click", () => performMotion("/api/resume", "从安全断点继续"));
byId("restart-button").addEventListener("click", () => performMotion("/api/restart", "从头绘制"));
byId("stop-button").addEventListener("click", async () => {
  byId("stop-button").disabled = true;
  try {
    const result = await api("/api/stop", { method: "POST" });
    byId("job-log").textContent = result.message;
    await pollJob();
  } catch (error) { byId("job-log").textContent = `停止请求失败：${error.message}。紧急情况请按物理急停。`; updateActions(); }
});

(async () => {
  try {
    const data = await api("/api/gallery");
    state.drawings = data.drawings;
    state.selected = state.drawings[0]?.id || null;
    renderGallery(); renderSelection();
    await pollJob();
    setInterval(pollJob, 1500);
  } catch (error) { byId("job-log").textContent = `无法载入画廊：${error.message}`; }
})();
