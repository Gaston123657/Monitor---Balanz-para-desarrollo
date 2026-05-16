"use strict";

const REFRESH_MS = 30 * 1000;

const MESES_ABBR = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

// Columnas a esconder en el frontend (server las manda igual, pero
// el v4 aprobado las saca por redundancia con el ticker).
const DROP_KEYS_BY_MONITOR = {
  bonares:   new Set(["name", "maturity"]),
  bopreales: new Set(["name", "maturity"]),
};

// Columnas con mini-barra (las que tienen signo).
const BAR_KINDS = new Set(["percent_signed", "scenario"]);

// Paleta para el chart de la curva soberana (idem style.css).
const CHART = {
  NAVY:        "#0a1d4a",
  NAVY_DARK:   "#06143b",
  ACCENT_BLUE: "#3a5fcf",
  BOPREAL:     "#1aa094",  // teal para 3ra serie BOPREALES
  TEXT_DIM:    "#4a5780",
  GRID:        "#e6ecf5",
  BORDER:      "#d2d8e6",
};

// Tickers excluidos de la curva (distorsionan por estar a vto inminente).
const CURVA_EXCLUDED_TICKERS = new Set(["BPY6D"]);

// Instancia del chart de curva (singleton; se actualiza en cada refresh).
let curvaChart = null;

// =====================================================================
// Formato
// =====================================================================

const fmt = {
  number(v, dec = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    return Number(v).toLocaleString("es-AR", {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    });
  },
  percent(v, dec = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    return `${Number(v).toLocaleString("es-AR", {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    })}%`;
  },
  percentSigned(v, dec = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    const n = Number(v);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toLocaleString("es-AR", {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    })}%`;
  },
  volume(v) {
    if (v === null || v === undefined || Number.isNaN(v) || Number(v) === 0) return "–";
    const n = Number(v);
    if (n >= 1e9) return `${(n / 1e9).toFixed(2).replace(".", ",")} B`;
    if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(0)} K`;
    return n.toFixed(0);
  },
  text(v) {
    if (v === null || v === undefined) return "–";
    return String(v);
  },
  // "30-abr-26"
  dateV4(d) {
    const dd = String(d.getDate()).padStart(2, "0");
    const mes = MESES_ABBR[d.getMonth()];
    const yy = String(d.getFullYear()).slice(-2);
    return `${dd}-${mes}-${yy}`;
  },
  // "14:32:18"
  timeHMS(d) {
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map((n) => String(n).padStart(2, "0"))
      .join(":");
  },
};

// =====================================================================
// Render de celdas
// =====================================================================

function columnMaxAbs(rows, key) {
  let max = 0;
  for (const row of rows) {
    const v = row[key];
    if (v === null || v === undefined) continue;
    const n = Number(v);
    if (Number.isFinite(n)) {
      const a = Math.abs(n);
      if (a > max) max = a;
    }
  }
  return max || 1;
}

function renderCell(col, value, ctx) {
  const td = document.createElement("td");

  if (value === null || value === undefined) {
    td.textContent = "–";
    td.classList.add("empty");
    if (col.kind === "text" || col.kind === "date") td.classList.add("col-text");
    if (col.key === "ticker") td.classList.add("ticker");
    return td;
  }

  switch (col.kind) {
    case "text":
      td.classList.add("col-text");
      td.textContent = fmt.text(value);
      if (col.key === "ticker") td.classList.add("ticker");
      return td;

    case "date":
      td.classList.add("col-text");
      td.textContent = fmt.text(value);
      return td;

    case "number":
      td.textContent = fmt.number(value, col.decimals ?? 2);
      return td;

    case "volume":
      td.textContent = fmt.volume(value);
      return td;

    case "percent":
      td.textContent = fmt.percent(value, col.decimals ?? 2);
      return td;

    case "percent_signed":
    case "scenario": {
      const dec = col.decimals ?? (col.kind === "scenario" ? 1 : 2);
      const n = Number(value);
      const text = fmt.percentSigned(n, dec);

      td.classList.add("has-bar");
      if (col.kind === "scenario") td.classList.add("scenario");
      if (n > 0)      td.classList.add("pos");
      else if (n < 0) td.classList.add("neg");

      const maxAbs = ctx.maxAbsByCol.get(col.key) || 1;
      const ratio = Math.min(Math.abs(n) / maxAbs, 1);
      const pct = (ratio * 100).toFixed(1);

      const track = document.createElement("div");
      track.className = "bar-track";
      const fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.width = `${pct}%`;
      track.appendChild(fill);

      const span = document.createElement("span");
      span.className = "cell-text";
      span.textContent = text;

      td.appendChild(track);
      td.appendChild(span);
      return td;
    }

    default:
      td.textContent = String(value);
      return td;
  }
}

// =====================================================================
// Render de un panel
// =====================================================================

function renderPanel(panel, monitor) {
  panel.classList.remove("loading", "error");
  if (monitor.status === "loading") panel.classList.add("loading");
  if (monitor.status === "error")   panel.classList.add("error");

  const sub  = panel.querySelector("[data-role='subtitle']");
  const ts   = panel.querySelector("[data-role='ts']");
  const body = panel.querySelector("[data-role='body']");

  sub.textContent = monitor.subtitle || "";
  ts.textContent = monitor.ts
    ? `Act. ${fmt.timeHMS(new Date(monitor.ts))}`
    : "—";

  body.innerHTML = "";
  if (monitor.status !== "ok") return;
  if (!monitor.rows || monitor.rows.length === 0) {
    body.innerHTML = `<div style="padding:14px 16px;color:var(--text-dim)">Sin datos.</div>`;
    return;
  }

  // Filtrado de columnas redundantes (name/maturity en bonares y bopreales)
  const drop = DROP_KEYS_BY_MONITOR[monitor.id] || new Set();
  const cols = monitor.columns.filter((c) => !drop.has(c.key));

  // Pre-calculo max abs por columna con barra
  const maxAbsByCol = new Map();
  for (const c of cols) {
    if (BAR_KINDS.has(c.kind)) {
      maxAbsByCol.set(c.key, columnMaxAbs(monitor.rows, c.key));
    }
  }
  const ctx = { maxAbsByCol };

  const table = document.createElement("table");
  table.className = "bonds";

  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  cols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.label;
    if (col.kind === "text" || col.kind === "date") th.classList.add("col-text");
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  monitor.rows.forEach((row) => {
    const tr = document.createElement("tr");
    cols.forEach((col) => {
      tr.appendChild(renderCell(col, row[col.key], ctx));
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  body.appendChild(table);
}

// =====================================================================
// Render del panel CURVA SOBERANA (Chart.js scatter + smooth line)
// Usa los datos del monitor 'comparacion_tir' (TIR vs DM).
// =====================================================================

function splitBySeries(points) {
  const al = [], gd = [];
  for (const p of points) {
    const t = String(p.ticker).toUpperCase();
    if (t.startsWith("AL") || t.startsWith("AE")) al.push(p);
    else if (t.startsWith("GD")) gd.push(p);
  }
  al.sort((a, b) => a.x - b.x);
  gd.sort((a, b) => a.x - b.x);
  return { al, gd };
}

// Regresion logaritmica y = a + b * ln(x) por minimos cuadrados.
// Devuelve {a, b} o null si no se puede ajustar.
function fitLogCurve(points) {
  if (!points || points.length < 2) return null;
  const lnXs = [], ys = [];
  for (const p of points) {
    if (!(p.x > 0) || !Number.isFinite(p.y)) return null;
    lnXs.push(Math.log(p.x));
    ys.push(p.y);
  }
  const n = points.length;
  const meanLnX = lnXs.reduce((a, b) => a + b, 0) / n;
  const meanY   = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (lnXs[i] - meanLnX) * (ys[i] - meanY);
    den += (lnXs[i] - meanLnX) ** 2;
  }
  if (den === 0) return null;
  const b = num / den;
  const a = meanY - b * meanLnX;
  return { a, b };
}

// Para puntos clusterizados (cerca entre si en x,y), apila las labels
// verticalmente con un offset incremental para evitar overlap.
// Devuelve array de offsets (px) alineado con `series`.
function computeLabelOffsets(series, baseOffset, thresholdX = 0.20,
                              thresholdY = 0.5, step = 14) {
  if (!series || !series.length) return [];
  const out = [];
  for (let i = 0; i < series.length; i++) {
    let cluster = 0;
    for (let j = 0; j < i; j++) {
      const dx = Math.abs(series[i].x - series[j].x);
      const dy = Math.abs(series[i].y - series[j].y);
      if (dx < thresholdX && dy < thresholdY) cluster++;
    }
    out.push(baseOffset + cluster * step);
  }
  return out;
}

// Genera N puntos a lo largo de la curva log (entre min y max de xs).
function logCurvePoints(points, n = 100) {
  const fit = fitLogCurve(points);
  if (!fit) return [];
  const xs = points.map((p) => p.x);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  if (!(xMax > xMin)) return [];
  const step = (xMax - xMin) / (n - 1);
  const out = [];
  for (let i = 0; i < n; i++) {
    const x = xMin + i * step;
    out.push({ x, y: fit.a + fit.b * Math.log(x) });
  }
  return out;
}

// Construye los datasets de Chart.js para una serie (puntos + linea log).
function curvaDatasets(series, color, label, labelAlign) {
  if (!series || series.length === 0) return [];
  // Offset base segun alineacion (top -> negativo en datalabels conven., bot -> positivo)
  const baseOffset = 8;
  const offsets = computeLabelOffsets(series, baseOffset);
  return [
    {
      // Puntos reales
      label,
      data: series,
      showLine: false,
      backgroundColor: color,
      borderColor:     color,
      pointRadius: 6,
      pointHoverRadius: 9,
      datalabels: {
        align: labelAlign, anchor: "center",
        // offset por punto (apila labels en clusters)
        offset: (ctx) => offsets[ctx.dataIndex] ?? baseOffset,
        color,
        font: { weight: 700, size: 11 },
        formatter: (v) => v.ticker,
      },
    },
    {
      // Curva log (oculta del legend con "_line_" prefix)
      label: `_line_${label}`,
      data: logCurvePoints(series),
      showLine: true,
      borderColor: color,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 0,
      backgroundColor: "transparent",
      tension: 0,
      datalabels: { display: false },
    },
  ];
}

function renderCurvaPanel(panel, bonaresMonitor, bopMonitor) {
  panel.classList.remove("loading", "error");
  if (bonaresMonitor.status === "loading") { panel.classList.add("loading"); return; }
  if (bonaresMonitor.status === "error")   { panel.classList.add("error");   return; }

  const sub    = panel.querySelector("[data-role='subtitle']");
  const ts     = panel.querySelector("[data-role='ts']");
  const canvas = panel.querySelector("[data-role='canvas']");

  // Puntos AL/AE/GD desde bonares (bonares row schema: ticker, tir, duration, ...)
  const sovPoints = (bonaresMonitor.rows || [])
    .map((row) => ({ ticker: row.ticker, x: row.duration, y: row.tir }))
    .filter((p) => p.x != null && p.y != null
                 && !CURVA_EXCLUDED_TICKERS.has(String(p.ticker).toUpperCase()));

  // Puntos BOPREALES (excluimos BPY6D que esta a vto -> TIR -93%)
  const bpRows = (bopMonitor && bopMonitor.rows) || [];
  const bopr = bpRows
    .map((row) => ({ ticker: row.ticker, x: row.duration, y: row.tir }))
    .filter((p) => p.x != null && p.y != null
                 && !CURVA_EXCLUDED_TICKERS.has(String(p.ticker).toUpperCase()))
    .sort((a, b) => a.x - b.x);

  const { al, gd } = splitBySeries(sovPoints);

  const totalBonos = al.length + gd.length + bopr.length;
  sub.textContent = `${totalBonos} bonos · regresión logarítmica · TIR vs Duration`;
  ts.textContent  = bonaresMonitor.ts
    ? `Act. ${fmt.timeHMS(new Date(bonaresMonitor.ts))}`
    : "—";

  const datasets = [
    ...curvaDatasets(al,   CHART.NAVY,        "Ley Argentina (AL/AE)", "top"),
    ...curvaDatasets(gd,   CHART.ACCENT_BLUE, "Ley NY (GD)",            "bottom"),
    ...curvaDatasets(bopr, CHART.BOPREAL,     "BOPREALES",              "bottom"),
  ];

  // Update incremental si ya existe la instancia
  if (curvaChart) {
    curvaChart.data.datasets = datasets;
    curvaChart.update("none");
    return;
  }

  // Primera vez: registrar plugin de datalabels y crear el chart
  if (window.Chart && window.ChartDataLabels) {
    Chart.register(ChartDataLabels);
  }

  curvaChart = new Chart(canvas.getContext("2d"), {
    type: "scatter",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 24, right: 16, bottom: 8, left: 8 } },
      scales: {
        x: {
          title: {
            display: true,
            text: "Duration Modificada (años)",
            color: CHART.TEXT_DIM,
            font: { weight: 700, size: 12 },
          },
          ticks: { color: CHART.TEXT_DIM, font: { size: 11 } },
          grid:  { color: CHART.GRID },
        },
        y: {
          title: {
            display: true,
            text: "Rendimiento (TIR %)",
            color: CHART.TEXT_DIM,
            font: { weight: 700, size: 12 },
          },
          ticks: {
            color: CHART.TEXT_DIM,
            font: { size: 11 },
            callback: (v) => `${Number(v).toFixed(1)}%`,
          },
          grid: { color: CHART.GRID },
        },
      },
      plugins: {
        legend: {
          display: true,
          position: "top",
          align: "end",
          labels: {
            color: CHART.NAVY_DARK,
            font: { weight: 700, size: 11 },
            boxWidth: 12, boxHeight: 12,
            usePointStyle: true,
            // Oculta los datasets de la curva (label "_line_..." )
            filter: (item) => !item.text.startsWith("_line_"),
          },
        },
        tooltip: {
          backgroundColor: CHART.NAVY,
          titleColor: "#fff",
          bodyColor: "#fff",
          padding: 10,
          // Solo tooltips en los datasets de puntos (no en la linea de regresion)
          filter: (item) => !item.dataset.label.startsWith("_line_"),
          callbacks: {
            title: (items) => items[0].raw.ticker,
            label: (item) =>
              `TIR ${item.raw.y.toFixed(2)}%  ·  DM ${item.raw.x.toFixed(2)} años`,
          },
        },
        datalabels: { padding: 4 },
      },
    },
  });
}

// =====================================================================
// Header (fecha + live indicator)
// =====================================================================

function setBrandDate(d = new Date()) {
  document.getElementById("brand-date").textContent = fmt.dateV4(d);
}

function setLiveStatus(state, ts) {
  // state: "ok" | "loading" | "error"
  const block = document.getElementById("live-block");
  block.classList.remove("ok", "loading", "error");
  block.classList.add(state);

  const timeEl = document.getElementById("live-time");
  if (state === "ok" && ts) {
    timeEl.textContent = fmt.timeHMS(new Date(ts));
  } else if (state === "loading") {
    timeEl.textContent = "—";
  }
  // En error mantenemos el ultimo timestamp valido (no piso)
}

// =====================================================================
// Render global + fetch
// =====================================================================

function renderFxStrip(fx) {
  const el = document.getElementById("fx-strip");
  if (!el) return;
  if (!fx || Object.keys(fx).length === 0) {
    el.innerHTML = '<span class="fx-empty">Cargando cotizaciones USD…</span>';
    return;
  }
  const ORDER = ["oficial", "mayorista", "blue", "bolsa", "contadoconliqui", "cripto", "tarjeta"];
  const num = (v) => v != null
    ? Number(v).toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";
  const parts = [];
  for (const casa of ORDER) {
    const q = fx[casa];
    if (!q) continue;
    const nombre = q.nombre || casa;
    parts.push(
      `<div class="fx-quote">
         <span class="fx-name">${nombre}</span>
         <div class="fx-prices">
           <span class="fx-side"><span class="fx-side-label">Compra</span><span class="fx-val">$${num(q.compra)}</span></span>
           <span class="fx-side"><span class="fx-side-label">Venta</span><span class="fx-val">$${num(q.venta)}</span></span>
         </div>
       </div>`
    );
  }
  el.innerHTML = parts.join("");
}

function renderAll(snapshot) {
  let anyError = false;
  let anyLoading = false;

  renderFxStrip(snapshot.fx || {});

  snapshot.monitors.forEach((m) => {
    if (m.status === "error")   anyError = true;
    if (m.status === "loading") anyLoading = true;
    const panel = document.querySelector(`.panel[data-id='${m.id}']`);
    if (panel) renderPanel(panel, m);
  });

  // Curva soberana: panel virtual que combina AL/AE + GD desde el monitor
  // bonares (3 colores: AL/AE, GD, BOPREALES).
  const bnr = snapshot.monitors.find((m) => m.id === "bonares");
  const bp  = snapshot.monitors.find((m) => m.id === "bopreales");
  const curvaPanel = document.querySelector(".panel[data-id='curva_soberana']");
  if (curvaPanel && bnr) renderCurvaPanel(curvaPanel, bnr, bp);

  if (anyError)        setLiveStatus("error", snapshot.ts);
  else if (anyLoading) setLiveStatus("loading", snapshot.ts);
  else                 setLiveStatus("ok", snapshot.ts);
}

async function fetchSnapshot() {
  try {
    const r = await fetch("/api/snapshot", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    renderAll(j);
  } catch (e) {
    console.warn("snapshot fetch fallo:", e);
    setLiveStatus("error");
  }
}

// =====================================================================
// Botones de screenshot (Capturar / WhatsApp)
// =====================================================================

function downloadCanvas(canvas, filename) {
  const link = document.createElement("a");
  link.href = canvas.toDataURL("image/png");
  link.download = filename;
  link.click();
}

function todayStamp() {
  const d = new Date();
  return `${fmt.dateV4(d)}_${fmt.timeHMS(d).replace(/:/g, "")}`;
}

async function captureFiel() {
  const btn = document.getElementById("btn-capture");
  btn.disabled = true;
  document.body.classList.add("capturing");
  try {
    const canvas = await html2canvas(document.body, {
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      scale: 2,             // mas resolucion
      useCORS: true,
      logging: false,
    });
    downloadCanvas(canvas, `monitor_${todayStamp()}.png`);
  } catch (e) {
    console.error("capture fallo:", e);
    alert("No se pudo generar la captura: " + e.message);
  } finally {
    document.body.classList.remove("capturing");
    btn.disabled = false;
  }
}

async function captureWhatsApp() {
  const btn = document.getElementById("btn-whatsapp");
  btn.disabled = true;
  document.body.classList.add("wa-mode", "capturing");
  // Esperar 2 frames para que el reflow se aplique antes del screenshot
  await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
  // El chart de Chart.js redibuja al cambiar el ancho del contenedor.
  // Forzamos el resize y esperamos otro frame para que termine el render.
  if (curvaChart) {
    curvaChart.resize();
    await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
  }
  try {
    const canvas = await html2canvas(document.body, {
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      scale: 1,
      useCORS: true,
      logging: false,
      windowWidth: 1080,
    });
    downloadCanvas(canvas, `monitor_wa_${todayStamp()}.png`);
  } catch (e) {
    console.error("capture wa fallo:", e);
    alert("No se pudo generar la captura WhatsApp: " + e.message);
  } finally {
    document.body.classList.remove("wa-mode", "capturing");
    btn.disabled = false;
  }
}

// =====================================================================
// Bootstrap
// =====================================================================

function init() {
  setBrandDate();
  // Refresca la fecha del header cada minuto (por si pasa medianoche)
  setInterval(setBrandDate, 60 * 1000);

  document.getElementById("btn-capture").addEventListener("click", captureFiel);
  document.getElementById("btn-whatsapp").addEventListener("click", captureWhatsApp);

  fetchSnapshot();
  setInterval(fetchSnapshot, REFRESH_MS);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
