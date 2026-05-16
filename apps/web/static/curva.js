"use strict";

// =====================================================================
// Curva Soberana - Pagina standalone de prueba
// Plotea TIR (Y) vs Duration Modificada (X) de los 11 bonos AL/GD
// del monitor "comparacion_tir". Refresh cada 30s.
// =====================================================================

const REFRESH_MS = 30 * 1000;

const MESES_ABBR = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

// Paleta Balanz (idem style.css)
const NAVY        = "#0a1d4a";
const NAVY_DARK   = "#06143b";
const ACCENT_BLUE = "#3a5fcf";
const TEXT_DIM    = "#4a5780";
const GRID_COLOR  = "#e6ecf5";
const POINT_AL    = "#0a1d4a";  // Ley Argentina (navy)
const POINT_GD    = "#3a5fcf";  // Ley NY (accent blue)

// =====================================================================
// Formato
// =====================================================================

function fmtDate(d) {
  const dd = String(d.getDate()).padStart(2, "0");
  const mes = MESES_ABBR[d.getMonth()];
  const yy = String(d.getFullYear()).slice(-2);
  return `${dd}-${mes}-${yy}`;
}

function fmtTime(d) {
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

// =====================================================================
// Build / Update del chart
// =====================================================================

let chart = null;

function splitBySeries(points) {
  const al = [], gd = [];
  for (const p of points) {
    const t = p.ticker.toUpperCase();
    if (t.startsWith("AL") || t.startsWith("AE")) al.push(p);
    else if (t.startsWith("GD")) gd.push(p);
  }
  // Cada serie ordenada por DM para que la linea se dibuje en orden
  al.sort((a, b) => a.x - b.x);
  gd.sort((a, b) => a.x - b.x);
  return { al, gd };
}

function buildChart(points) {
  const ctx = document.getElementById("curva-chart").getContext("2d");
  Chart.register(ChartDataLabels);

  const { al, gd } = splitBySeries(points);

  const datasetAL = {
    label: "Ley Argentina (AL/AE)",
    data: al,
    showLine: true,
    tension: 0.35,
    backgroundColor: POINT_AL,
    borderColor: POINT_AL,
    borderWidth: 2,
    pointRadius: 6,
    pointHoverRadius: 9,
    datalabels: {
      align: "top",
      anchor: "center",
      offset: 8,
      color: NAVY_DARK,
      font: { weight: 700, size: 11 },
      formatter: (val) => val.ticker,
    },
  };

  const datasetGD = {
    label: "Ley NY (GD)",
    data: gd,
    showLine: true,
    tension: 0.35,
    backgroundColor: POINT_GD,
    borderColor: POINT_GD,
    borderWidth: 2,
    pointRadius: 6,
    pointHoverRadius: 9,
    datalabels: {
      align: "bottom",
      anchor: "center",
      offset: 8,
      color: ACCENT_BLUE,
      font: { weight: 700, size: 11 },
      formatter: (val) => val.ticker,
    },
  };

  if (chart) {
    chart.data.datasets[0].data = al;
    chart.data.datasets[1].data = gd;
    chart.update();
    return;
  }

  chart = new Chart(ctx, {
    type: "scatter",
    data: { datasets: [datasetAL, datasetGD] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 24, right: 20, bottom: 8, left: 8 } },
      scales: {
        x: {
          title: {
            display: true,
            text: "Duration Modificada (años)",
            color: TEXT_DIM,
            font: { weight: 700, size: 12 },
          },
          ticks: { color: TEXT_DIM, font: { size: 11 } },
          grid: { color: GRID_COLOR },
          beginAtZero: false,
        },
        y: {
          title: {
            display: true,
            text: "Rendimiento (TIR %)",
            color: TEXT_DIM,
            font: { weight: 700, size: 12 },
          },
          ticks: {
            color: TEXT_DIM,
            font: { size: 11 },
            callback: (v) => `${Number(v).toFixed(1)}%`,
          },
          grid: { color: GRID_COLOR },
        },
      },
      plugins: {
        legend: {
          display: true,
          position: "top",
          align: "end",
          labels: {
            color: NAVY_DARK,
            font: { weight: 700, size: 11 },
            boxWidth: 12,
            boxHeight: 12,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: NAVY,
          titleColor: "#fff",
          bodyColor: "#fff",
          padding: 10,
          callbacks: {
            title: (items) => items[0].raw.ticker,
            label: (item) => {
              const p = item.raw;
              return `TIR ${p.y.toFixed(2)}%  ·  DM ${p.x.toFixed(2)} años`;
            },
          },
        },
        datalabels: {
          // las opciones default; cada dataset puede override
          padding: 4,
        },
      },
    },
  });
}

// =====================================================================
// Header live indicator
// =====================================================================

function setLiveStatus(state, ts) {
  const block = document.getElementById("live-block");
  block.classList.remove("ok", "loading", "error");
  block.classList.add(state);
  const timeEl = document.getElementById("live-time");
  if (state === "ok" && ts) timeEl.textContent = fmtTime(new Date(ts));
  else if (state === "loading") timeEl.textContent = "—";
}

// =====================================================================
// Fetch + render
// =====================================================================

async function refresh() {
  try {
    const r = await fetch("/api/snapshot", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const snap = await r.json();
    const ct = snap.monitors.find((m) => m.id === "comparacion_tir");

    if (!ct || ct.status !== "ok") {
      setLiveStatus("loading", snap.ts);
      return;
    }

    const points = ct.rows
      .map((row) => ({
        ticker: row.ticker,
        x: row.dm,
        y: row.tir,
      }))
      .filter((p) => p.x != null && p.y != null);

    buildChart(points);

    setLiveStatus("ok", snap.ts);
    document.getElementById("curva-ts").textContent = ct.ts
      ? `Act. ${fmtTime(new Date(ct.ts))}`
      : "—";
    document.getElementById("curva-sub").textContent =
      `${points.length} bonos AL/GD · TIR vs Duration Modificada`;
  } catch (e) {
    console.error("refresh fallo:", e);
    setLiveStatus("error");
  }
}

function init() {
  document.getElementById("brand-date").textContent = fmtDate(new Date());
  setInterval(() => {
    document.getElementById("brand-date").textContent = fmtDate(new Date());
  }, 60 * 1000);
  refresh();
  setInterval(refresh, REFRESH_MS);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
