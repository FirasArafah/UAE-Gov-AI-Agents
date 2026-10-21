// 1) بيانات وهمية (لاحقاً رح تيجي من سيرفر زميلك)
const AGENTS = [
  { id: "data", name: "وكيل فحص البيانات", summary: "1,000 سجل، 3 أعمدة حسّاسة" },
  { id: "fair", name: "وكيل مقاييس العدالة", summary: "نسبة الأثر المتباين 0.67" },
  { id: "cf", name: "وكيل الحالات المقابلة", summary: "14% من القرارات تغيّرت عند تبديل الجنسية فقط" },
  { id: "rep", name: "وكيل التقرير", summary: "تم إعداد التقرير" }
];

const RESULT = {
  groups: [
    { name: "دول الخليج", approval: 0.82 },
    { name: "أوروبا", approval: 0.79 },
    { name: "جنوب آسيا", approval: 0.61 },
    { name: "أفريقيا", approval: 0.55 }
  ],
  report: "أظهر النظام فجوة قبول واضحة بين المجموعات، وتبقى الفجوة بعد ضبط الدخل والتعليم. نوصي بمراجعة بشرية للحالات المرفوضة وإعادة معايرة النموذج."
};

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

renderPipeline({});