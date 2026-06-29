"""Parser del JSONL capturado por `bymadata_capture_addon.py`.

Lee la captura del tráfico del Add-in de BYMADATA y produce un informe markdown
REDACTADO (sin credenciales/tokens) en `BYMADATA_EXCEL/CAPTURE-FINDINGS.md`:
hosts, endpoint(s) de autenticación, flujo de auth (grant/headers), endpoints de
datos (con content-type y forma de respuesta) y WebSockets. Eso alcanza para
completar `core/infrastructure/bymadata_provider.py`.

Uso:
    py -3.12 scripts/bymadata_parse_capture.py <ruta-al-capture.jsonl>
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_MD = os.path.join(ROOT, "BYMADATA_EXCEL", "CAPTURE-FINDINGS.md")

# Pistas de endpoint de autenticación.
AUTH_HINT = re.compile(r"(token|oauth|auth|login|connect|signin|sign-in|jwt|session)", re.I)
# Claves cuyo valor hay que redactar en cuerpos JSON / x-www-form-urlencoded.
SECRET_KEYS = re.compile(
    r"(password|client_secret|access_token|refresh_token|id_token|secret|pwd|"
    r"authorization|api[_-]?key)", re.I)


def redact(text):
    if not text:
        return text
    # JSON: "clave":"valor"  → "clave":"***"
    text = re.sub(r'("(?:' + SECRET_KEYS.pattern + r')"\s*:\s*)"[^"]*"',
                  r'\1"***"', text, flags=re.I)
    # form-urlencoded: clave=valor → clave=***
    text = re.sub(r'((?:' + SECRET_KEYS.pattern + r')=)[^&\s]+',
                  r'\1***', text, flags=re.I)
    # Bearer xxx → Bearer ***
    text = re.sub(r'(Bearer\s+)[A-Za-z0-9._\-]+', r'\1***', text)
    return text


def redact_headers(h):
    if not isinstance(h, dict):
        return h
    out = {}
    for k, v in h.items():
        out[k] = "***" if SECRET_KEYS.search(k) else v
    return out


def short(text, n=600):
    if not text:
        return text
    text = text.strip()
    return text if len(text) <= n else text[:n] + " …(truncado)"


def main(path):
    if not os.path.exists(path):
        print(f"No existe la captura: {path}")
        return 1
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass

    http_recs = [r for r in recs if r.get("kind") == "http"]
    ws_starts = [r for r in recs if r.get("kind") == "ws_start"]
    ws_msgs = [r for r in recs if r.get("kind") == "ws_msg"]

    hosts = defaultdict(int)
    for r in http_recs:
        hosts[r.get("host", "?")] += 1
    for r in ws_starts:
        hosts[r.get("host", "?")] += 1

    auth = [r for r in http_recs if AUTH_HINT.search(r.get("path", "") or "")
            or AUTH_HINT.search(r.get("url", "") or "")
            or "grant_type" in (r.get("req_body") or "")]
    data = [r for r in http_recs if r not in auth]

    L = []
    L.append("# BYMADATA — hallazgos de la captura de tráfico\n")
    L.append("Generado por `scripts/bymadata_parse_capture.py` (REDACTADO: sin "
             "credenciales ni tokens). Insumo para completar `bymadata_provider.py`.\n")
    L.append(f"- Flows HTTP: {len(http_recs)} · auth-candidatos: {len(auth)} · "
             f"datos: {len(data)} · WebSocket starts: {len(ws_starts)}\n")

    L.append("\n## Hosts vistos (frecuencia)\n")
    for h, n in sorted(hosts.items(), key=lambda kv: -kv[1]):
        L.append(f"- `{h}` — {n}")

    L.append("\n## Autenticación (candidatos)\n")
    if not auth:
        L.append("_No se detectaron endpoints de auth obvios. Revisar manualmente "
                 "el JSONL crudo._")
    for r in auth:
        L.append(f"\n### `{r.get('method')} {r.get('url')}` → {r.get('status')}")
        L.append(f"- content-type resp: `{r.get('resp_ctype')}`")
        L.append("- req headers (redactado):")
        L.append(f"  ```\n  {json.dumps(redact_headers(r.get('req_headers')), indent=2, ensure_ascii=False)}\n  ```")
        if r.get("req_body"):
            L.append(f"- req body (redactado): `{short(redact(r['req_body']), 300)}`")
        if r.get("resp_body"):
            L.append(f"- resp body (redactado): `{short(redact(r['resp_body']), 400)}`")

    L.append("\n## Endpoints de datos\n")
    seen = set()
    for r in data:
        key = (r.get("method"), r.get("url", "").split("?")[0])
        if key in seen:
            continue
        seen.add(key)
        L.append(f"\n### `{r.get('method')} {r.get('url')}` → {r.get('status')}")
        L.append(f"- content-type resp: `{r.get('resp_ctype')}`")
        if r.get("req_body"):
            L.append(f"- req body (redactado): `{short(redact(r['req_body']), 300)}`")
        if r.get("resp_body"):
            L.append(f"- resp body (redactado): `{short(redact(r['resp_body']), 500)}`")

    if ws_starts:
        L.append("\n## WebSockets\n")
        for r in ws_starts:
            L.append(f"- handshake: `{r.get('url')}`")
        L.append(f"- mensajes WS capturados: {len(ws_msgs)} "
                 f"(ver JSONL crudo; muestra redactada abajo)")
        for r in ws_msgs[:5]:
            origen = "cliente" if r.get("from_client") else "servidor"
            L.append(f"  - [{origen}] `{short(redact(r.get('content')), 200)}`")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"Informe escrito en {OUT_MD}")
    print(f"Hosts: {dict(hosts)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: py -3.12 scripts/bymadata_parse_capture.py <capture.jsonl>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
