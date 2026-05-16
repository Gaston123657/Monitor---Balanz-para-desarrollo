# 🎨 Dark Financial Dashboard - Design System Guide

**Version:** 1.0.0  
**Theme:** Dark Mode - High Contrast Financial Data Dashboard  
**Created:** 2026-05-08

---

## 📋 Índice

1. [Introducción](#introducción)
2. [Estructura de Archivos](#estructura-de-archivos)
3. [Paleta de Colores](#paleta-de-colores)
4. [Componentes](#componentes)
5. [Cómo Usar](#cómo-usar)
6. [Ejemplos](#ejemplos)
7. [Variables CSS](#variables-css)
8. [Personalización](#personalización)

---

## 📌 Introducción

Este **Design System** es un conjunto reusable de estilos CSS y componentes para crear dashboards financieros con tema oscuro. 

### Características:
- ✅ **Tema Oscuro** - Optimizado para datos financieros
- ✅ **Zebra Striping** - Filas alternas para legibilidad
- ✅ **Color Semántico** - Verde (+), Rojo (-)
- ✅ **Responsive** - Mobile-friendly
- ✅ **Accesible** - WCAG AA compliant
- ✅ **Variables CSS** - Fácil de personalizar

---

## 📁 Estructura de Archivos

```
MONITOR WEB/
├── dark-financial-dashboard.css    # Estilos reutilizables
├── design-system.json             # Configuración de colores y spacing
├── template-dashboard.html        # Template HTML de ejemplo
└── DESIGN-SYSTEM-GUIDE.md        # Este archivo
```

---

## 🎨 Paleta de Colores

### Fondos

| Nombre | Color | Uso |
|--------|-------|-----|
| `--bg-dark` | `#0b1230` | Fondo principal |
| `--bg-darker` | `#050915` | Fondo más oscuro |
| `--bg-table-header` | `#111e55` | Headers de tablas |
| `--bg-table-alt1` | `#0f1a47` | Filas pares |
| `--bg-table-alt2` | `#0b1230` | Filas impares |

### Textos

| Nombre | Color | Uso |
|--------|-------|-----|
| `--text-white` | `white` | Títulos principales |
| `--text-light` | `#e6ecff` | Texto principal |
| `--text-subtitle` | `#a8b4ff` | Subtítulos |
| `--text-muted` | `#7a85cc` | Texto atenuado |

### Semánticos

| Nombre | Color | Uso |
|--------|-------|-----|
| `--color-positive` | `#6CFF8F` | Valores positivos (+) |
| `--color-negative` | `#FF6B6B` | Valores negativos (-) |
| `--color-neutral` | `#a8b4ff` | Neutral/Info |
| `--color-warning` | `#FFD93D` | Advertencias |
| `--color-info` | `#6CB4FF` | Información |

---

## 🧩 Componentes

### Headers

```html
<header class="dfd-header">
    <div class="dfd-header-title">Título Principal</div>
    <div class="dfd-header-subtitle">Subtítulo</div>
    <div class="dfd-header-time">Actualizado: ...</div>
</header>
```

### Tablas

```html
<table class="dfd-table">
    <thead class="dfd-table-header">
        <tr>
            <th>Columna 1</th>
            <th>Columna 2</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Dato</td>
            <td><span class="dfd-positive">+5.3%</span></td>
        </tr>
    </tbody>
</table>
```

### Cards/Paneles

```html
<div class="dfd-card">
    <div class="dfd-card-title">Título del Card</div>
    <div class="dfd-card-content">Contenido aquí</div>
</div>
```

### Grillas

```html
<section class="dfd-grid">
    <div class="dfd-card">Card 1</div>
    <div class="dfd-card">Card 2</div>
    <div class="dfd-card">Card 3</div>
</section>
```

---

## 🚀 Cómo Usar

### 1. Copiar archivos

```bash
cp dark-financial-dashboard.css tu-proyecto/
cp design-system.json tu-proyecto/
```

### 2. Importar CSS en tu HTML

```html
<head>
    <link rel="stylesheet" href="dark-financial-dashboard.css">
</head>
```

### 3. Usar clases en el HTML

```html
<body>
    <header class="dfd-header">
        <div class="dfd-header-title">Mi Dashboard</div>
    </header>
    
    <main class="dfd-container">
        <table class="dfd-table">
            <thead class="dfd-table-header">
                <tr>
                    <th>Bono</th>
                    <th>Precio</th>
                    <th>Variación</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>AL29</td>
                    <td>63.49</td>
                    <td><span class="dfd-positive">+0.78%</span></td>
                </tr>
            </tbody>
        </table>
    </main>
</body>
```

---

## 📝 Ejemplos

### Ejemplo 1: Valor Positivo

```html
<span class="dfd-positive">+5.30%</span>
```
Resultado: Texto en verde brillante (#6CFF8F)

### Ejemplo 2: Valor Negativo

```html
<span class="dfd-negative">-2.15%</span>
```
Resultado: Texto en rojo suave (#FF6B6B)

### Ejemplo 3: Fondo Coloreado

```html
<span class="dfd-bg-positive">Activo</span>
<span class="dfd-bg-negative">Inactivo</span>
```
Resultado: Fondo semitransparente + texto coloreado

### Ejemplo 4: Tabla Completa

```html
<table class="dfd-table">
    <thead class="dfd-table-header">
        <tr>
            <th>Ticker</th>
            <th>Last</th>
            <th>TIR</th>
            <th>Var 7d</th>
            <th>Estado</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>AL29</td>
            <td>63.49</td>
            <td>8.50%</td>
            <td><span class="dfd-positive">+0.78%</span></td>
            <td><span class="dfd-positive">✓ Activo</span></td>
        </tr>
        <tr>
            <td>BPY6</td>
            <td>38.35</td>
            <td>10.45%</td>
            <td><span class="dfd-negative">-2.15%</span></td>
            <td><span class="dfd-warning">⚠ Atención</span></td>
        </tr>
    </tbody>
</table>
```

---

## 🎯 Variables CSS

Todas las variables están definidas en `:root`. Puedes sobrescribirlas en tu CSS:

```css
:root {
    --bg-dark: #0b1230;
    --color-positive: #6CFF8F;
    --color-negative: #FF6B6B;
    --font-size-title: 20px;
    /* ... más variables */
}
```

### Cambiar Paleta Completa

```css
:root {
    /* Cambiar a tema más claro */
    --bg-dark: #1a1a2e;
    --bg-table-header: #16213e;
    --text-light: #eeeeee;
    --color-positive: #00d084;
    --color-negative: #ff3333;
}
```

---

## 🎨 Personalización

### 1. Cambiar Colores

Edita las variables CSS en `dark-financial-dashboard.css`:

```css
:root {
    --color-positive: #00FF00;  /* Tu color verde */
    --color-negative: #FF0000;  /* Tu color rojo */
}
```

### 2. Cambiar Tipografía

```css
:root {
    --font-primary: "Your Font Name", sans-serif;
    --font-size-table: 12px;
    --font-size-title: 24px;
}
```

### 3. Ajustar Espaciado

```css
:root {
    --spacing-md: 20px;  /* Más espacio */
    --spacing-sm: 10px;
}
```

### 4. Agregar Temas Adicionales

```css
/* Crear un tema "alto contraste" */
@media (prefers-contrast: more) {
    :root {
        --text-light: #ffffff;
        --bg-dark: #000000;
        --color-positive: #00FF00;
        --color-negative: #FF0000;
    }
}

/* Crear un tema claro */
body.light-mode {
    --bg-dark: #ffffff;
    --text-light: #000000;
    --bg-table-header: #f5f5f5;
    --color-positive: #2ecc71;
    --color-negative: #e74c3c;
}
```

---

## 🔧 Clases Disponibles

### Estructura
- `.dfd-header` - Header principal
- `.dfd-container` - Contenedor centrado
- `.dfd-grid` - Grid responsivo
- `.dfd-card` - Panel/Card
- `.dfd-table` - Tabla

### Colores de Texto
- `.dfd-positive` - Verde
- `.dfd-negative` - Rojo
- `.dfd-neutral` - Lavanda
- `.dfd-warning` - Amarillo
- `.dfd-info` - Azul

### Fondos Coloreados
- `.dfd-bg-positive` - Fondo verde semitransparente
- `.dfd-bg-negative` - Fondo rojo semitransparente

### Tipografía
- `.dfd-font-bold` - Negrita
- `.dfd-font-medium` - Peso medio
- `.dfd-text-monospace` - Fuente monoespaciada

### Alineación
- `.dfd-text-center` - Centro
- `.dfd-text-right` - Derecha

### Bordes
- `.dfd-border` - Borde completo
- `.dfd-border-top` - Borde superior
- `.dfd-border-bottom` - Borde inferior
- `.dfd-divider` - Línea divisoria

### Animaciones
- `.dfd-fade-in` - Aparecer gradualmente
- `.dfd-slide-in` - Deslizar hacia abajo

---

## 📱 Responsive

El design system es mobile-friendly. Los breakpoints son:

```css
@media (max-width: 768px) {
    /* Ajustes automáticos para móvil */
    .dfd-grid {
        grid-template-columns: 1fr;
    }
}
```

---

## ♿ Accesibilidad

- ✅ Alto contraste (WCAG AA)
- ✅ Soporte para modo alto contraste
- ✅ Soporte para "prefers-reduced-motion"
- ✅ Tablas semánticas con `<thead>`, `<tbody>`
- ✅ Texto alternativo para iconos

---

## 🚀 Quick Start

**1. Copia estos 2 archivos a tu proyecto:**
```
dark-financial-dashboard.css
design-system.json
```

**2. Importa el CSS en tu HTML:**
```html
<link rel="stylesheet" href="dark-financial-dashboard.css">
```

**3. Usa el template como base:**
```
Abre template-dashboard.html y úsalo como referencia
```

**4. Personaliza los colores:**
```css
:root {
    --color-positive: tu-color-verde;
    --color-negative: tu-color-rojo;
}
```

---

## 📧 Soporte

Para preguntas o mejoras, contacta al equipo de desarrollo.

---

**Made with 💙 for financial data dashboards**
