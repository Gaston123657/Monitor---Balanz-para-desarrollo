// Detalle Dólar Futuro — página standalone que renderiza los paneles
// `dlr_carry` y `dlr_cobertura` (chart de líneas + tabla) leyendo /api/snapshot.
// Self-contained (no depende de app.js), consistente con cierre.html / bcra.html.
//
// Mejoras de disposición pedidas:
//   1) El contrato más cercano (menor días al vto, ej. dólar junio) se OMITE del
//      gráfico — su tasa anualizada se distorsiona con pocos días — pero se
//      mantiene en la tabla.
//   2) El eje TEA de costo de cobertura (y el eje del carry) se ajusta apretado
//      al rango de datos graficados, para que el cambio contrato a contrato sea
//      apreciable en lugar de quedar aplastado por el front month.

(function () {
  "use strict";

  const REFRESH_MS = 5000;
  const ORANGE = "#e0a73c"; // TEA pesos / costo cobertura (TEA)

  // Paleta theme-aware (sin depender de app.js).
  function palette() {
    const dark = document.documentElement.getAttribute("data-theme") !== "light";
    return dark
      ? { TEXT_DIM: "#aab4d4", GRID: "rgba(255,255,255,0.10)", NAVY: "#102452", BLUE: "#6486e6" }
      : { TEXT_DIM: "#4a5780", GRID: "#e6ecf5", NAVY: "#0a1d4a", BLUE: "#3a5fcf" };
  }

  const fmt = {
    number(v, dec = 2) {
      if (v === null || v === undefined || Number.isNaN(v)) return "–";
      return Number(v).toLocaleString("es-AR",
        { minimumFractionDigits: dec, maximumFractionDigits: dec });
    },
    percent(v, dec = 2) {
      if (v === null || v === undefined || Number.isNaN(v)) return "–";
      return `${fmt.number(v, dec)}%`;
    },
    percentSigned(v, dec = 2) {
      if (v === null || v === undefined || Number.isNaN(v)) return "–";
      const n = Number(v);
      return `${n > 0 ? "+" : ""}${fmt.number(n, dec)}%`;
    },
    volume(v) {
      if (v === null || v === undefined || Number.isNaN(v) || Number(v) === 0) return "–";
      const n = Number(v);
      if (n >= 1e9) return `${(n / 1e9).toFixed(2).replace(".", ",")} B`;
      if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
      if (n >= 1e3) return `${(n / 1e3).toFixed(0)} K`;
      return n.toFixed(0);
    },
  };

  // Celda de tabla según el `kind` del schema (subset de los kinds del dashboard).
  function cell(col, value) {
    const td = document.createElement("td");
    if (col.align === "center") td.classList.add("col-center");
    if (value === null || value === undefined) {
      td.textContent = "–";
      td.classList.add("empty");
      if (col.kind === "text") td.classList.add("col-text");
      return td;
    }
    const dec = col.decimals;
    switch (col.kind) {
      case "text":
        td.classList.add("col-text");
        td.textContent = String(value);
        break;
      case "date":
        // El backend serializa fechas como "YYYY-MM-DD" → mostrar "dd/mm/yy".
        td.classList.add("col-text");
        {
          const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
          td.textContent = m ? `${m[3]}/${m[2]}/${m[1].slice(2)}` : String(value);
        }
        break;
      case "percent":
        td.textContent = fmt.percent(value, dec ?? 2);
        break;
      case "percent_signed": {
        const n = Number(value);
        td.textContent = fmt.percentSigned(n, dec ?? 2);
        td.style.fontWeight = "600";
        td.style.color = n > 0 ? "#4ec07e" : n < 0 ? "#e06a70" : "";
        break;
      }
      case "volume":
        td.textContent = fmt.volume(value);
        break;
      case "number":
      default:
        td.textContent = fmt.number(value, dec ?? 2);
        break;
    }
    return td;
  }

  function buildTable(monitor) {
    const table = document.createElement("table");
    table.className = "bonds";
    const cols = monitor.columns || [];

    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    cols.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c.label;
      if (c.kind === "text") th.classList.add("col-text");
      if (c.align === "center") th.classList.add("col-center");
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    (monitor.rows || []).forEach((row) => {
      const tr = document.createElement("tr");
      cols.forEach((c) => tr.appendChild(cell(c, row[c.key])));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  // Filas a graficar: ordenadas por días y SIN el front month (más cercano).
  // Se mantiene >=2 puntos para que el chart tenga sentido.
  function chartRows(rows) {
    const sorted = rows.slice().sort((a, b) => (a.dias || 0) - (b.dias || 0));
    return sorted.length > 2 ? sorted.slice(1) : sorted;
  }

  // Bounds apretados a partir de una o más series (ignora null), con padding.
  function tightBounds(series, pad) {
    const vals = [];
    series.forEach((arr) => arr.forEach((v) => {
      if (v !== null && v !== undefined && Number.isFinite(Number(v))) vals.push(Number(v));
    }));
    if (!vals.length) return {};
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    const p = pad != null ? pad : span * 0.18;
    return { suggestedMin: lo - p, suggestedMax: hi + p };
  }

  const axis = (P, text, extra) => Object.assign({
    title: { display: !!text, text, color: P.TEXT_DIM, font: { weight: 700, size: 11 } },
    ticks: { color: P.TEXT_DIM, font: { size: 10 } },
    grid: { color: P.GRID },
  }, extra || {});

  const legend = (P) => ({
    display: true, position: "top", align: "end",
    labels: { color: P.TEXT_DIM, font: { size: 10 }, boxWidth: 16, padding: 10 },
  });

  const charts = {};

  function prep(panel, monitor) {
    const sub = panel.querySelector("[data-role='subtitle']");
    const tableMount = panel.querySelector("[data-role='synth-table']");
    const canvas = panel.querySelector("[data-role='canvas']");
    if (sub) sub.textContent = monitor.subtitle || "";
    panel.classList.remove("loading", "error");
    if (monitor.status !== "ok") {
      panel.classList.add(monitor.status === "error" ? "error" : "loading");
      return null;
    }
    if (tableMount) { tableMount.innerHTML = ""; tableMount.appendChild(buildTable(monitor)); }
    const rows = monitor.rows || [];
    if (!canvas || rows.length < 2) return null;
    if (window.Chart && window.ChartDataLabels) { try { Chart.register(ChartDataLabels); } catch (e) {} }
    return { canvas, rows };
  }

  function renderCarry(panel, monitor) {
    const ready = prep(panel, monitor);
    if (!ready) return;
    const P = palette();
    const rows = chartRows(ready.rows);
    const labels = rows.map((r) => r.label);
    const pesos = rows.map((r) => r.tea_pesos);
    const fut = rows.map((r) => r.tea_fut);
    const datasets = [
      { label: "TEA pesos (tasa fija)", data: pesos,
        borderColor: ORANGE, backgroundColor: ORANGE, pointBackgroundColor: ORANGE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.25, spanGaps: true, datalabels: { display: false } },
      { label: "TEA futuro (deval impl.)", data: fut,
        borderColor: P.BLUE, backgroundColor: P.BLUE, pointBackgroundColor: P.BLUE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.25, spanGaps: true, datalabels: { display: false } },
    ];
    const yb = tightBounds([pesos, fut]);
    if (charts.carry) {
      charts.carry.data.labels = labels;
      charts.carry.data.datasets = datasets;
      Object.assign(charts.carry.options.scales.y, yb);
      charts.carry.update("none");
      return;
    }
    charts.carry = new Chart(ready.canvas.getContext("2d"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(P, ""),
          y: axis(P, "TEA %", Object.assign({
            ticks: { color: P.TEXT_DIM, font: { size: 10 }, callback: (v) => `${fmt.number(v, 1)}%` },
          }, yb)),
        },
        plugins: {
          legend: legend(P), datalabels: { display: false },
          tooltip: {
            backgroundColor: P.NAVY, titleColor: "#fff", bodyColor: "#fff", padding: 10,
            callbacks: { label: (it) => `${it.dataset.label}: ${it.parsed.y != null ? fmt.number(it.parsed.y, 2) + "%" : "–"}` },
          },
        },
      },
    });
  }

  function renderCobertura(panel, monitor) {
    const ready = prep(panel, monitor);
    if (!ready) return;
    const P = palette();
    const rows = chartRows(ready.rows);
    const labels = rows.map((r) => r.label);
    const fx = rows.map((r) => r.dolar_futuro);
    const tea = rows.map((r) => r.costo_cob_tea);
    const datasets = [
      { label: "Dólar futuro ($/USD)", data: fx, yAxisID: "yFx",
        borderColor: P.BLUE, backgroundColor: P.BLUE, pointBackgroundColor: P.BLUE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.15, datalabels: { display: false } },
      { label: "Costo cobertura (TEA)", data: tea, yAxisID: "yTea",
        borderColor: ORANGE, backgroundColor: ORANGE, pointBackgroundColor: ORANGE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.25, datalabels: { display: false } },
    ];
    // Eje TEA apretado al rango (pad chico) → resalta el cambio contrato a contrato.
    const teaB = tightBounds([tea], 0.004);
    const fxB = tightBounds([fx]);
    if (charts.cob) {
      charts.cob.data.labels = labels;
      charts.cob.data.datasets = datasets;
      Object.assign(charts.cob.options.scales.yTea, teaB);
      Object.assign(charts.cob.options.scales.yFx, fxB);
      charts.cob.update("none");
      return;
    }
    charts.cob = new Chart(ready.canvas.getContext("2d"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(P, ""),
          yFx: axis(P, "$/USD", Object.assign({
            position: "left",
            ticks: { color: P.TEXT_DIM, font: { size: 10 }, callback: (v) => fmt.number(v, 0) },
          }, fxB)),
          yTea: axis(P, "TEA %", Object.assign({
            position: "right", grid: { drawOnChartArea: false },
            ticks: { color: P.TEXT_DIM, font: { size: 10 }, callback: (v) => `${fmt.number(v, 1)}%` },
          }, teaB)),
        },
        plugins: {
          legend: legend(P), datalabels: { display: false },
          tooltip: {
            backgroundColor: P.NAVY, titleColor: "#fff", bodyColor: "#fff", padding: 10,
            callbacks: {
              label: (it) => it.dataset.yAxisID === "yTea"
                ? `${it.dataset.label}: ${it.parsed.y != null ? fmt.number(it.parsed.y, 2) + "%" : "–"}`
                : `${it.dataset.label}: ${it.parsed.y != null ? fmt.number(it.parsed.y, 2) : "–"}`,
            },
          },
        },
      },
    });
  }

  // Sintético de tasa en pesos: una línea por instrumento DL (ordenado por
  // días). Compara la TNA sintética (DL + short futuro) contra la TNA fija
  // (curva LECAP/BONCAP) al mismo plazo. Se muestra en TNA (no TEA); la tabla
  // de abajo conserva su detalle. A diferencia del carry/cobertura, NO se omite
  // el primer punto: cada fila es un instrumento distinto, no un contrato de
  // futuro con front-month distorsionado.
  function renderSintetico(panel, monitor) {
    const ready = prep(panel, monitor);
    if (!ready) return;
    const P = palette();
    const rows = ready.rows.slice().sort((a, b) => (a.dias || 0) - (b.dias || 0));
    const labels = rows.map((r) => r.ticker);
    const sint = rows.map((r) => r.tna_sint);
    // Fallback: si el backend no manda tna_fija (server con código viejo),
    // derivarla de tea_fija con la misma convención base 365 (TEA→TNA). Ambos
    // valores llegan en unidades de % (ya escalados).
    const teaToTna = (tea) => (tea === null || tea === undefined || Number.isNaN(tea))
      ? null
      : 365 * (Math.pow(1 + tea / 100, 1 / 365) - 1) * 100;
    const fija = rows.map((r) => (r.tna_fija !== null && r.tna_fija !== undefined)
      ? r.tna_fija
      : teaToTna(r.tea_fija));
    const datasets = [
      { label: "Sintético TNA (DL + short futuro)", data: sint,
        borderColor: ORANGE, backgroundColor: ORANGE, pointBackgroundColor: ORANGE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.25, spanGaps: true, datalabels: { display: false } },
      { label: "Tasa fija TNA (curva)", data: fija,
        borderColor: P.BLUE, backgroundColor: P.BLUE, pointBackgroundColor: P.BLUE,
        borderWidth: 2.5, pointRadius: 3, tension: 0.25, spanGaps: true,
        borderDash: [5, 4], datalabels: { display: false } },
    ];
    const yb = tightBounds([sint, fija]);
    if (charts.sint) {
      charts.sint.data.labels = labels;
      charts.sint.data.datasets = datasets;
      Object.assign(charts.sint.options.scales.y, yb);
      charts.sint.update("none");
      return;
    }
    charts.sint = new Chart(ready.canvas.getContext("2d"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: axis(P, ""),
          y: axis(P, "TNA %", Object.assign({
            ticks: { color: P.TEXT_DIM, font: { size: 10 }, callback: (v) => `${fmt.number(v, 1)}%` },
          }, yb)),
        },
        plugins: {
          legend: legend(P), datalabels: { display: false },
          tooltip: {
            backgroundColor: P.NAVY, titleColor: "#fff", bodyColor: "#fff", padding: 10,
            callbacks: { label: (it) => `${it.dataset.label}: ${it.parsed.y != null ? fmt.number(it.parsed.y, 2) + "%" : "–"}` },
          },
        },
      },
    });
  }

  async function refresh() {
    const statusEl = document.getElementById("df-status");
    try {
      const r = await fetch("/api/snapshot", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const snap = await r.json();
      const carry = (snap.monitors || []).find((m) => m.id === "dlr_carry");
      const cob = (snap.monitors || []).find((m) => m.id === "dlr_cobertura");
      const sint = (snap.monitors || []).find((m) => m.id === "dlr_sintetico");
      const carryPanel = document.querySelector(".panel[data-id='dlr_carry']");
      const cobPanel = document.querySelector(".panel[data-id='dlr_cobertura']");
      const sintPanel = document.querySelector(".panel[data-id='dlr_sintetico']");
      if (carry && carryPanel) renderCarry(carryPanel, carry);
      if (cob && cobPanel) renderCobertura(cobPanel, cob);
      if (sint && sintPanel) renderSintetico(sintPanel, sint);
      if (statusEl) {
        const ts = snap.ts ? new Date(snap.ts).toLocaleTimeString("es-AR") : "";
        statusEl.textContent = ts ? `Actualizado ${ts}` : "En vivo";
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = "Error al actualizar — reintentando…";
    }
  }

  // ── Captura a PNG ──────────────────────────────────────────────────────
  // Misma mecánica que el "Capturar" del dashboard principal: html2canvas a
  // escala 4 sobre la página completa (header + ambos paneles + nota) y
  // descarga. El botón se oculta durante la captura vía `.capturing`.
  function todayStamp() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  }

  function downloadCanvas(canvas, filename) {
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = filename;
    link.click();
  }

  async function capturePage() {
    const page = document.querySelector(".df-page");
    const btn = document.getElementById("df-capture");
    if (!page || !window.html2canvas) return;
    if (btn) btn.disabled = true;
    page.classList.add("capturing");
    try {
      const canvas = await html2canvas(page, {
        backgroundColor: getComputedStyle(document.body).backgroundColor,
        scale: 4,
        useCORS: true,
      });
      downloadCanvas(canvas, `dolar_futuro_${todayStamp()}.png`);
    } catch (e) {
      console.error("captura de dólar futuro falló:", e);
      alert("No se pudo generar la captura: " + e.message);
    } finally {
      page.classList.remove("capturing");
      if (btn) btn.disabled = false;
    }
  }

  const captureBtn = document.getElementById("df-capture");
  if (captureBtn) captureBtn.addEventListener("click", capturePage);

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
