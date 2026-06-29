"""Addon de mitmproxy para capturar el tráfico del Add-in de Excel de BYMADATA.

Objetivo: descubrir host, flujo de autenticación y endpoints de datos que usa el
.xll (ExcelDNA/.NET), para completar `core/infrastructure/bymadata_provider.py`.

Filtra el ruido de Windows/Office/telemetría y loguea solo los flows "interesantes"
a un JSONL. Captura también handshakes y mensajes WebSocket (el tier Snapshot de
BYMADATA podría ser streaming). Trunca cuerpos a 8 KB.

Uso (ver scripts/bymadata_capture.md):
    set BYMADATA_CAPTURE_OUT=<ruta>\capture.jsonl
    .venv-capture\Scripts\mitmdump.exe -s scripts/bymadata_capture_addon.py

OJO: el JSONL puede contener credenciales y tokens en claro. Guardalo local, no lo
commitees. El parser (`bymadata_parse_capture.py`) redacta secretos en su informe.
"""
import json
import os

from mitmproxy import http, ctx

OUT = os.environ.get(
    "BYMADATA_CAPTURE_OUT",
    os.path.join(os.path.expanduser("~"), "bymadata_capture.jsonl"),
)
MAXLEN = 8192

# Hosts de ruido a ignorar (telemetría/OS/CDNs/PKI). Todo lo demás se loguea.
IGNORE = (
    "microsoft.com", "windows.com", "windowsupdate", "office.com", "office365.com",
    "officeapps.live.com", "officeclient", "msftconnecttest", "msedge", "edge.microsoft",
    "live.com", "msn.com", "bing.com", "azureedge", "aria.microsoft", "trafficmanager",
    "digicert", "verisign", "entrust", "globalsign", "sectigo", "ocsp", "crl",
    "google", "gstatic", "googleapis", "gvt1", "mozilla", "sfx.ms", "skype",
    "clients.config", "settings-win", "watson", "telemetry", "nel.cloudflare",
)


def _interesting(host: str) -> bool:
    h = (host or "").lower()
    return bool(h) and not any(x in h for x in IGNORE)


def _append(rec: dict) -> None:
    try:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover
        ctx.log.warn(f"bymadata_capture: no se pudo escribir: {e}")


def response(flow: http.HTTPFlow) -> None:
    if not _interesting(flow.request.host):
        return
    try:
        rec = {
            "kind": "http",
            "method": flow.request.method,
            "url": flow.request.pretty_url,
            "host": flow.request.host,
            "path": flow.request.path,
            "req_headers": dict(flow.request.headers),
            "req_body": flow.request.get_text(strict=False)[:MAXLEN] if flow.request.content else None,
            "status": flow.response.status_code if flow.response else None,
            "resp_ctype": flow.response.headers.get("content-type") if flow.response else None,
            "resp_body": flow.response.get_text(strict=False)[:MAXLEN] if (flow.response and flow.response.content) else None,
        }
        _append(rec)
        ctx.log.info(f"BYMA? {rec['method']} {rec['status']} {flow.request.pretty_url}")
    except Exception as e:  # pragma: no cover
        ctx.log.warn(f"bymadata_capture response err: {e}")


def websocket_start(flow: http.HTTPFlow) -> None:
    if not _interesting(flow.request.host):
        return
    _append({"kind": "ws_start", "url": flow.request.pretty_url,
             "host": flow.request.host, "req_headers": dict(flow.request.headers)})
    ctx.log.info(f"BYMA? WS START {flow.request.pretty_url}")


def websocket_message(flow: http.HTTPFlow) -> None:
    if not _interesting(flow.request.host):
        return
    try:
        msg = flow.websocket.messages[-1]
        content = msg.text if hasattr(msg, "text") else str(msg.content)
        _append({"kind": "ws_msg", "url": flow.request.pretty_url,
                 "from_client": msg.from_client, "content": content[:MAXLEN]})
    except Exception as e:  # pragma: no cover
        ctx.log.warn(f"bymadata_capture ws err: {e}")
