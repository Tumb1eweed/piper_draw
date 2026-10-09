const state = { drawings: [], selected: null, view: "preview", connectionOk: false, polling: null };

const byId = (id) => document.getElementById(id);
const gallery = byId("gallery");
const preview = byId("art-preview");
const drawButton = byId("draw-button");
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

function updateStartButton() {
  drawButton.disabled = !(state.selected && state.connectionOk && safetyConfirm.checked);
}

function renderSelection() {
  const drawing = selectedDrawing();
  document.querySelectorAll(".art-card").forEach((card) => card.classList.toggle("selected", card.dataset.id === state.selected));
  if (!drawing) return;
  byId("selected-title").textContent = drawing.title;
  byId("selected-description").textContent = drawing.subtitle;
  preview.src = `/${drawing[state.view]}?v=${encodeURIComponent(drawing.id)}`;
  preview.alt = `${drawing.title}${state.view === "preview" ? "轨迹" : "参考线稿"}`;
}

function renderGallery() {
  gallery.replaceChildren(...state.drawings.map((drawing) => {
    const button = document.createElement("button");
    button.className = "art-card";
    button.dataset.id = drawing.id;
    button.innerHTML = `<img src="/${drawing.preview}" alt="${drawing.title} 轨迹预览"><span>${drawing.title}</span><small>${drawing.subtitle}</small>`;
    button.addEventListener("click", () => { state.selected = drawing.id; renderSelection(); updateStartButton(); });
    return button;
  }));
}

function setConnection(result) {
  state.connectionOk = Boolean(result.available);
  byId("status-dot").classList.toggle("ok", state.connectionOk);
  byId("status-title").textContent = state.connectionOk ? "连接状态正常" : "连接未就绪";
  byId("status-detail").textContent = state.connectionOk ? `${result.can} · 已获得实时关节反馈` : (result.message || result.report || "请检查 CAN、供电和 WSL 挂载。");
  updateStartButton();
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
    byId("job-badge").textContent = job.active ? "作画中" : (job.returncode === 0 ? "已完成" : "空闲");
    byId("job-badge").classList.toggle("busy", job.active);
    byId("job-log").textContent = job.log.length ? job.log.join("\n") : "等待执行器输出。";
    if (!job.active && state.polling) { clearInterval(state.polling); state.polling = null; }
  } catch (error) { byId("job-log").textContent = `无法读取执行状态：${error.message}`; }
}

document.querySelectorAll(".view-button").forEach((button) => button.addEventListener("click", () => {
  state.view = button.dataset.view;
  document.querySelectorAll(".view-button").forEach((item) => item.classList.toggle("active", item === button));
  renderSelection();
}));
safetyConfirm.addEventListener("change", updateStartButton);
byId("status-button").addEventListener("click", refreshConnection);
drawButton.addEventListener("click", async () => {
  const drawing = selectedDrawing();
  if (!drawing || !confirm(`确认开始绘制《${drawing.title}》？`)) return;
  drawButton.disabled = true;
  try {
    const result = await api("/api/draw", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ drawing_id: drawing.id, confirmed: true }) });
    byId("job-log").textContent = result.message;
    await pollJob();
    state.polling = setInterval(pollJob, 1500);
  } catch (error) { byId("job-log").textContent = `未启动：${error.message}`; updateStartButton(); }
});

(async () => {
  try {
    const data = await api("/api/gallery");
    state.drawings = data.drawings;
    state.selected = state.drawings[0]?.id || null;
    renderGallery(); renderSelection();
  } catch (error) { byId("job-log").textContent = `无法载入画廊：${error.message}`; }
})();
