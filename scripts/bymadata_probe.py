"""Spike de descubrimiento del backend de BYMADATA (read-only).

Objetivo: averiguar CÓMO habla el Add-in de Excel de BYMADATA con el servidor, para
decidir si se puede replicar con `requests`/`websockets` (modo `rest`) o si el único
camino con lo contratado (solo Add-in) es el puente Excel/COM (modo `excel`).

Qué hace (no toca nada, no sale a internet):
  1. Extrae strings ASCII y UTF-16LE de los .xll de `BYMADATA_EXCEL/`.
  2. Detecta el framework del add-in (ExcelDNA / .NET) y filtra candidatos a
     host/URL/endpoint/auth.
  3. Escribe un informe en `BYMADATA_EXCEL/PROBE-FINDINGS.md`.

Uso:  py -3.12 scripts/bymadata_probe.py

Si el informe no revela el host (caso ExcelDNA con assembly empaquetado), los
siguientes pasos para confirmar el backend en vivo están documentados al final del
informe (captura de tráfico con Fiddler/mitmproxy, o lectura del .config en runtime).
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLL_DIR = os.path.join(ROOT, "BYMADATA_EXCEL")
OUT_MD = os.path.join(XLL_DIR, "PROBE-FINDINGS.md")

# Strings de interés: hosts/URLs/endpoints/auth del producto (no ruido de PKI/Windows).
INTEREST = re.compile(
    r"(https?://|wss?://|\.byma\b|byma|\.com\.ar|/api|api[-.]|/v\d|oauth|token|"
    r"client_id|client_secret|grant_type|login|endpoint|primary|matriz|realtime|"
    r"snapshot|delayed|/eod|appsettings|\.json|\.config)",
    re.I,
)
# Ruido conocido a descartar (cadenas de certificados, schemas, win api).
NOISE = re.compile(
    r"(digicert|excel-dna\.net|schemas\.microsoft|schemas\.openxmlformats|"
    r"w3\.org|mscorlib|api-ms-win|System\.|PublicKeyToken|ocsp\.|crl\d|cacerts)",
    re.I,
)


def _strings(data: bytes):
    asc = [s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{5,}", data)]
    u16 = [s.decode("utf-16le", "ignore")
           for s in re.findall(rb"(?:[\x20-\x7e]\x00){5,}", data)]
    return asc + u16


def probe_file(path: str) -> dict:
    data = open(path, "rb").read()
    allstr = _strings(data)
    is_exceldna = any("excel-dna.net" in s.lower() for s in allstr)
    candidates = sorted({
        s.strip() for s in allstr
        if INTEREST.search(s) and not NOISE.search(s) and 4 < len(s) < 200
    })
    # ¿Hay un host real (no schema) tipo https://algo.com.ar ?
    real_hosts = sorted({
        m.group(0) for s in allstr
        for m in [re.search(r"https?://[a-z0-9.\-]+\.[a-z]{2,}(?:/[^\s\"']*)?", s, re.I)]
        if m and not NOISE.search(m.group(0))
    })
    return {
        "path": path,
        "size": len(data),
        "is_exceldna": is_exceldna,
        "candidates": candidates,
        "real_hosts": real_hosts,
    }


def main() -> int:
    xlls = sorted(glob.glob(os.path.join(XLL_DIR, "*.xll")))
    if not xlls:
        print(f"No se encontraron .xll en {XLL_DIR}")
        return 1

    reports = [probe_file(p) for p in xlls]
    any_exceldna = any(r["is_exceldna"] for r in reports)
    any_real_host = any(r["real_hosts"] for r in reports)

    lines = []
    lines.append("# BYMADATA — informe de spike del backend\n")
    lines.append("Generado por `scripts/bymadata_probe.py` (read-only). Determina cómo "
                 "habla el Add-in de Excel con BYMADATA para elegir el modo del provider.\n")
    for r in reports:
        lines.append(f"\n## `{os.path.basename(r['path'])}` ({r['size']:,} bytes)\n")
        lines.append(f"- Framework ExcelDNA/.NET detectado: **{r['is_exceldna']}**")
        lines.append(f"- Hosts/URLs reales en texto plano: "
                     f"**{r['real_hosts'] if r['real_hosts'] else 'ninguno'}**")
        lines.append(f"- Candidatos (host/endpoint/auth, filtrado de ruido): "
                     f"{len(r['candidates'])}")
        for c in r["candidates"]:
            lines.append(f"  - `{c}`")

    lines.append("\n## Conclusión\n")
    if any_real_host:
        lines.append("Se hallaron hosts en texto plano (ver arriba). Evaluar replicar "
                     "el backend con `requests`/`websockets` (modo `rest`).")
    elif any_exceldna:
        lines.append(
            "El add-in es **ExcelDNA (.NET)**: el código que llama al backend vive en un "
            "**assembly .NET empaquetado** dentro del .xll (ExcelDNA lo comprime) y/o lee "
            "el host de un `.config`/AppSettings en runtime (`get_AppSettings`, `xlfLogin`). "
            "Por eso los endpoints NO aparecen en texto plano. Con lo contratado (solo "
            "Add-in), el acceso programático fiable hoy es el **puente Excel/COM** "
            "(`BYMADATA_MODE=excel`). El modo `rest` queda como scaffold inerte hasta "
            "obtener credenciales de la API REST o confirmar el backend por captura de tráfico.")
    else:
        lines.append("No se detectó ExcelDNA ni hosts en texto plano. Revisar manualmente.")

    lines.append("\n### Próximos pasos para confirmar el backend en vivo (opcional)\n")
    lines.append("1. **Captura de tráfico**: abrir Excel con el Add-in, loguearse y refrescar "
                 "una función BYMA con Fiddler/mitmproxy escuchando HTTPS. El host + endpoints "
                 "+ flujo de auth quedan a la vista. Si es replicable con las credenciales del "
                 "usuario, completar el modo `rest` del provider.")
    lines.append("2. **Config en runtime**: buscar el `.config`/AppSettings que el add-in lee "
                 "(`%APPDATA%`/junto al .xll) — suele tener el host base.")
    lines.append("3. **API REST oficial**: si se contrata, usar `client_id`/`client_secret` del "
                 "portal de desarrolladores contra `api-mgr.byma.com.ar` (modo `rest` directo).")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Informe escrito en {OUT_MD}")
    print(f"ExcelDNA: {any_exceldna} | hosts reales en texto plano: {any_real_host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
