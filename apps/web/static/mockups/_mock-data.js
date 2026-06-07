// Datos dummy compartidos para los 7 mockups de "Cierre de Mercado Onshore".
// Valores realistas para escenario mayo 2026 (mercado onshore AR).
window.MOCK_DATA = {
  timestamp: "29 MAY 2026 · 17:00 ARS",
  dolares: [
    { tipo: "Mayorista",  precio: 1116.50, delta: 0.18 },
    { tipo: "Oficial",    precio: 1132.00, delta: 0.22 },
    { tipo: "MEP",        precio: 1148.40, delta: -0.31 },
    { tipo: "CCL",        precio: 1156.20, delta:  0.12 },
    { tipo: "Blue",       precio: 1175.00, delta:  0.43 },
    { tipo: "Tarjeta",    precio: 1471.60, delta:  0.22 },
    { tipo: "Cripto",     precio: 1152.30, delta: -0.18 }
  ],
  bcra: {
    reservas_usd_mm:        38_750,
    reservas_delta_usd_mm:  +185,
    riesgo_pais_bps:        612,
    riesgo_pais_delta_bps:  -14
  },
  acciones: {
    ganadores: [
      { ticker: "GGAL", hoy: +3.42, mes:  +5.12, ytd: +18.40, precio:  8_540 },
      { ticker: "YPFD", hoy: +2.85, mes:  +9.20, ytd: +22.15, precio: 42_180 },
      { ticker: "BMA",  hoy: +2.61, mes:  +3.85, ytd: +15.20, precio: 12_450 },
      { ticker: "PAMP", hoy: +1.93, mes:  +1.40, ytd:  +7.85, precio:  6_220 },
      { ticker: "ALUA", hoy: +1.48, mes:  -2.10, ytd:  +4.30, precio:  1_890 }
    ],
    perdedores: [
      { ticker: "EDN",  hoy: -2.85, mes:  -4.30, ytd:  -8.20, precio:  3_240 },
      { ticker: "TRAN", hoy: -2.10, mes:  -1.85, ytd:  +2.10, precio:  4_180 },
      { ticker: "COME", hoy: -1.62, mes:  -3.40, ytd:  -5.20, precio:    285 },
      { ticker: "TXAR", hoy: -1.20, mes:  +2.10, ytd:  +8.50, precio:    945 },
      { ticker: "BBAR", hoy: -0.85, mes:  -0.40, ytd:  +6.20, precio:  7_820 }
    ]
  },
  soberanos: {
    globales: {
      ganadores: [
        { ticker: "GD29", tir: 9.85,  delta: -0.42 },
        { ticker: "GD30", tir: 10.20, delta: -0.28 },
        { ticker: "GD35", tir: 11.05, delta: -0.18 }
      ],
      perdedores: [
        { ticker: "GD46", tir: 11.85, delta: +0.21 },
        { ticker: "GD41", tir: 11.45, delta: +0.12 }
      ]
    },
    bonares: {
      ganadores: [
        { ticker: "AL30", tir: 10.85, delta: -0.35 },
        { ticker: "AL35", tir: 11.60, delta: -0.22 },
        { ticker: "AL29", tir: 10.40, delta: -0.18 }
      ],
      perdedores: [
        { ticker: "AL41", tir: 12.10, delta: +0.15 }
      ]
    },
    bopreales: {
      ganadores: [
        { ticker: "BPY26", tir:  7.20, delta: -0.18 },
        { ticker: "BPC7",  tir:  8.45, delta: -0.10 }
      ],
      perdedores: [
        { ticker: "BPD7",  tir:  9.10, delta: +0.08 }
      ]
    }
  },
  renta_fija: {
    cer: {
      ganadores: [
        { ticker: "TZX26", tir:  4.85, delta: -0.18 },
        { ticker: "TZXD6", tir:  5.20, delta: -0.12 },
        { ticker: "TX28",  tir:  5.85, delta: -0.08 }
      ],
      perdedores: [
        { ticker: "TZX27", tir:  5.45, delta: +0.10 }
      ]
    },
    lecaps: {
      ganadores: [
        { ticker: "S30J5", tem: 2.45, tna: 29.40, delta: -0.08 },
        { ticker: "S15G5", tem: 2.38, tna: 28.56, delta: -0.05 },
        { ticker: "S31O5", tem: 2.31, tna: 27.72, delta: -0.03 }
      ],
      perdedores: [
        { ticker: "S28N5", tem: 2.28, tna: 27.36, delta: +0.04 }
      ]
    },
    tamar_puro: {
      ganadores: [
        { ticker: "TTM26", tir: 32.40, delta: -0.45 },
        { ticker: "TTJ26", tir: 31.85, delta: -0.30 }
      ],
      perdedores: [
        { ticker: "TTS26", tir: 33.10, delta: +0.18 }
      ]
    }
  },
  futuros: [
    { contrato: "DLR May26", precio: 1118.50, delta: +0.18, tna:  6.40 },
    { contrato: "DLR Jun26", precio: 1138.20, delta: +0.22, tna:  7.85 },
    { contrato: "DLR Jul26", precio: 1162.40, delta: +0.15, tna:  9.10 },
    { contrato: "DLR Ago26", precio: 1188.80, delta: +0.12, tna: 10.25 }
  ]
};

// Helpers compartidos
window.fmt = {
  num:   (v, d=2) => v == null ? "—" : v.toLocaleString("es-AR", {minimumFractionDigits:d, maximumFractionDigits:d}),
  pct:   (v, d=2) => v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(d) + "%",
  bps:   (v)      => v == null ? "—" : (v >= 0 ? "+" : "") + v + " bps",
  cls:   (v)      => v == null ? "" : (v >= 0 ? "pos" : "neg"),
  arrow: (v)      => v == null ? "" : (v >= 0 ? "▲" : "▼")
};
