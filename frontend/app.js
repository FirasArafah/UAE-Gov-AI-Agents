// 1) بيانات وهمية (لاحقاً رح تيجي من سيرفر زميلك)
let AGENTS = [];
let RESULT = {};

async function loadData() {
  const response = await fetch("../shared/audit-result.example.json");
  const data = await response.json();
  AGENTS = data.agents;
  RESULT = { groups: data.groups, report: data.report };
}

// 2) عناصر الصفحة
const runButton = document.getElementById("run");
const pipeline = document.getElementById("pipeline");
const results = document.getElementById("results");
const verdict = document.getElementById("verdict");
const bars = document.getElementById("bars");
const report = document.getElementById("report");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 3) رسم مراحل الوكلاء
function renderPipeline(status) {
  pipeline.innerHTML = AGENTS.map(function (a) {
    const s = status[a.id] || "idle";
    let text = "بانتظار البدء";
    if (s === "running") text = "قيد العمل…";
    if (s === "done") text = a.summary;
    return `<li class="${s}">
      <i class="dot"></i>
      <div><b>${a.name}</b><span>${text}</span></div>
    </li>`;
  }).join("");
}

// 4) رسم النتائج
function renderResults() {
  const rates = RESULT.groups.map((g) => g.approval);
  const max = Math.max(...rates);
  const min = Math.min(...rates);
  const biased = min / max < 0.8;

  verdict.className = biased ? "bad" : "ok";
  verdict.textContent = biased
    ? "تم رصد تحيّز: مجموعة أو أكثر دون حدّ الـ80%"
    : "لم يُرصد تحيّز: كل المجموعات ضمن الحد";

  bars.innerHTML = RESULT.groups.map(function (g) {
    const ratio = g.approval / max;
    let color = "var(--ok)";
    if (ratio < 0.9) color = "var(--warn)";
    if (ratio < 0.8) color = "var(--bad)";
    return `<div class="row">
      <span class="name">${g.name}</span>
      <div class="track">
        <div class="fill" style="width:${g.approval * 100}%; background:${color}"></div>
        <div class="mark" style="right:${max * 80}%"></div>
      </div>
      <span class="pct">${Math.round(g.approval * 100)}%</span>
    </div>`;
  }).join("");

  report.textContent = RESULT.report;
  results.hidden = false;
}

// 5) تشغيل التدقيق
runButton.addEventListener("click", async function () {
  await loadData();
  runButton.disabled = true;
  results.hidden = true;
  const status = {};
  renderPipeline(status);

  for (const a of AGENTS) {
    status[a.id] = "running";
    renderPipeline(status);
    await sleep(1000);
    status[a.id] = "done";
    renderPipeline(status);
  }

  renderResults();
  runButton.disabled = false;
});


const fileInput = document.getElementById("file");
const fileInfo = document.getElementById("fileInfo");

fileInput.addEventListener("change", async function () {
  const file = fileInput.files[0];
  if (!file) return;
  const text = await file.text();
  const lines = text.trim().split(/\r?\n/);
  const columns = lines[0].split(",");
  fileInfo.textContent =
    "الملف: " + file.name +
    " | عدد السجلات: " + (lines.length - 1) +
    " | الأعمدة: " + columns.join("، ");

  const preview = document.getElementById("preview");
  const table = document.createElement("table");

  const head = table.insertRow();
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    head.appendChild(th);
  }

  for (const line of lines.slice(1, 6)) {
    const row = table.insertRow();
    for (const cell of line.split(",")) {
      row.insertCell().textContent = cell;
    }
  }

  preview.innerHTML = "";
  preview.appendChild(table);
});

loadData().then(function () {
  renderPipeline({});
});