/* =====================================================================
   Run ONs · Cotizaciones — arma el documento imprimible a partir de
   /api/ons_run. Documento de reporte (no panel del dashboard): una sola
   tabla continua con thead repetido por página, bandas por sector y
   sub-encabezados por emisor. "PDF" = Imprimir → Guardar como PDF.
   ===================================================================== */
(function () {
  "use strict";

  // Columnas del Run (Clase omitida — no está en la base).
  var COLS = [
    { key: "ticker",     label: "Título",    cls: "l tk" },
    { key: "ley",        label: "Ley",       cls: "l" },
    { key: "tipo",       label: "Tipo",      cls: "l" },
    { key: "calif",      label: "Calif.",    cls: "l" },
    { key: "emision",    label: "Emisión",   cls: "l" },
    { key: "vto",        label: "Vto",       cls: "l" },
    { key: "cupon",      label: "Cupón",     cls: "num" },
    { key: "frec",       label: "Frec.",     cls: "l" },
    { key: "dias_cup",   label: "Días cup.", cls: "num" },
    { key: "price",      label: "Precio",    cls: "num" },
    { key: "parity",     label: "Paridad",   cls: "num" },
    { key: "tir",        label: "TIR",       cls: "num" },
    { key: "cy",         label: "CY",        cls: "num" },
    { key: "md",         label: "MD",        cls: "num" },
    { key: "convex",     label: "Convex.",   cls: "num" },
    { key: "change_pct", label: "%Día",      cls: "num" },
    { key: "volume",     label: "Vol",       cls: "num" },
  ];

  // Paleta de acentos por sector (barra izquierda de la franja).
  var SECTOR_ACCENTS = [
    "#6cb4ff", "#ffd93d", "#6cff8f", "#ff8f6c", "#c79bff",
    "#5fe0d0", "#ff9ec4", "#a0d468", "#f6bb42", "#7c9bff",
  ];

  // ---- Formateadores es-AR ----
  function nf(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return Number(v).toLocaleString("es-AR", {
      minimumFractionDigits: dec, maximumFractionDigits: dec,
    });
  }
  function pct(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return nf(v, dec) + "%";
  }
  function pctSigned(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    var s = (v > 0 ? "+" : "") + nf(v, dec) + "%";
    return s;
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    var p = String(iso).slice(0, 10).split("-"); // yyyy-mm-dd
    if (p.length !== 3) return "—";
    return p[2] + "/" + p[1] + "/" + p[0].slice(2);
  }
  function fmtDateLong(iso) {
    if (!iso) return "";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return "";
    return p[2] + "/" + p[1] + "/" + p[0];
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  // Tramo de color por calificación (escala nacional FIXscr): A* fuerte,
  // BBB grado de inversión, BB/B especulativo, C/D distress.
  function ratingClass(v) {
    var s = String(v).toUpperCase().replace(/\(ARG\)/, "").trim();
    if (s.indexOf("AA") === 0 || s.indexOf("A") === 0) return "rt-a";
    if (s.indexOf("BBB") === 0) return "rt-bbb";
    if (s.indexOf("BB") === 0 || s.indexOf("B") === 0) return "rt-b";
    if (s.indexOf("C") === 0 || s.indexOf("D") === 0) return "rt-d";
    return "";
  }

  // ---- Render de una celda de ON ----
  function cell(row, col) {
    var v = row[col.key];
    var cls = col.cls;
    var txt;
    switch (col.key) {
      case "cupon":      txt = (v == null) ? "—" : pct(v * 100, 2); break;
      case "frec":       txt = esc(row.frec_label || ""); break;
      case "dias_cup":   txt = (v == null) ? "—" : nf(v, 0); break;
      case "price":      txt = nf(v, 2); break;
      case "parity":     txt = pct(v, 1); break;
      case "tir":        txt = pct(v, 2); break;
      case "cy":         txt = pct(v, 2); break;
      case "md":         txt = nf(v, 2); break;
      case "convex":     txt = nf(v, 2); break;
      case "volume":     txt = (v == null) ? "—" : nf(v, 0); break;
      case "emision":    txt = fmtDate(v); break;
      case "vto":        txt = fmtDate(v); break;
      case "change_pct":
        txt = pctSigned(v, 2);
        if (v > 0) cls += " pos"; else if (v < 0) cls += " neg";
        break;
      case "calif":
        if (v == null) {
          txt = '<span class="muted">s/c</span>';
        } else {
          var tip = row.calif_persp
            ? esc(row.calif_persp + (row.calif_fecha ? " · " + row.calif_fecha : ""))
            : "";
          txt = '<span class="rt ' + ratingClass(v) + '"' +
                (tip ? ' title="' + tip + '"' : "") + ">" + esc(v) + "</span>";
        }
        break;
      default:           txt = esc(v == null ? "—" : v);
    }
    return '<td class="' + cls + '">' + txt + "</td>";
  }

  function render(data) {
    var sheet = document.getElementById("sheet");
    var nCols = COLS.length;

    if (!data.sectors || !data.sectors.length || !data.total) {
      sheet.innerHTML = '<div class="empty">No hay cotizaciones de ONs disponibles ' +
        'todavía. Esperá a que los paneles de ONs del dashboard estén poblados ' +
        'y volvé a actualizar.</div>';
      return;
    }

    var html = "";
    // Encabezado del documento
    html += '<div class="doc-head">';
    html += '<div class="title">Obligaciones Negociables · <small>Renta Fija Argentina</small></div>';
    html += '<div class="meta">Precios Dólar MEP · ' + fmtDateLong(data.as_of) +
            "<br>" + data.total + " ONs · " + data.sectors.length + " sectores</div>";
    html += "</div>";

    // Tabla
    html += '<table class="run"><thead><tr>';
    COLS.forEach(function (c) {
      html += '<th class="' + (c.cls.indexOf("l") === 0 ? "l" : "") + '">' +
              esc(c.label) + "</th>";
    });
    html += "</tr></thead><tbody>";

    data.sectors.forEach(function (sec, si) {
      var accent = SECTOR_ACCENTS[si % SECTOR_ACCENTS.length];
      var stats = "TIR prom " + pct(sec.tir_prom, 2) + " · MD prom " + nf(sec.md_prom, 2);
      var counts = sec.count + " ONs (AR " + sec.count_ar + " · EXT " + sec.count_ext + ")";
      html += '<tr class="sector-band"><td colspan="' + nCols + '" style="--sec-accent:' +
              accent + '">' +
              '<span class="sec-name">' + esc(sec.sector) + " · " + counts + "</span>" +
              '<span class="sec-stats">' + stats + "</span></td></tr>";

      sec.issuers.forEach(function (iss) {
        html += '<tr class="issuer"><td colspan="' + nCols + '">' +
                esc(iss.name) + ' <span class="cnt">(' + iss.count + ")</span></td></tr>";
        iss.rows.forEach(function (row, ri) {
          // Striping explícito (no depende de :nth-child(of)); alterna dentro
          // de cada emisor para que las clases largas se lean parejas.
          html += '<tr class="on' + (ri % 2 ? " alt" : "") + '">';
          COLS.forEach(function (c) { html += cell(row, c); });
          html += "</tr>";
        });
      });
    });

    html += "</tbody></table>";

    // Pie del documento
    var gen = data.generated_utc ? data.generated_utc.replace("T", " ").replace("+00:00", "") : "";
    html += '<div class="doc-foot">Generado ' + esc(gen) +
            " UTC · Fuente: Data912 / BYMA · Precios indicativos, no constituye " +
            "oferta de compra/venta.</div>";

    sheet.innerHTML = html;

    // Pie repetido en impresión
    document.getElementById("print-foot").textContent =
      "Obligaciones Negociables · Renta Fija Argentina · Precios Dólar MEP " +
      fmtDateLong(data.as_of) + " · Fuente: Data912 / BYMA · Precios indicativos.";
  }

  function setStatus(txt) {
    var el = document.getElementById("status");
    if (el) el.textContent = txt;
  }

  function load() {
    setStatus("Cargando…");
    fetch("/api/ons_run", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        render(data);
        setStatus(data.total + " ONs · " + data.sectors.length + " sectores · " +
                  fmtDateLong(data.as_of));
        // Auto-imprimir si se abrió con ?print=1
        if (/[?&]print=1\b/.test(location.search)) {
          setTimeout(function () { window.print(); }, 400);
        }
      })
      .catch(function (e) {
        setStatus("Error: " + e.message);
        document.getElementById("sheet").innerHTML =
          '<div class="empty">No se pudo cargar el Run de ONs: ' + esc(e.message) +
          "</div>";
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("btn-print").addEventListener("click", function () {
      window.print();
    });
    document.getElementById("btn-reload").addEventListener("click", load);
    load();
  });
})();
