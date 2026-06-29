"""Tests del matcheo de calificaciones FIXscr (core/infrastructure/ons_ratings).

Sin Excel real: arma un xlsx temporal con un puñado de entidades y verifica el
matcheo determinístico (exacto, substring seguro, alias) y — crítico — el bloqueo
de falsos positivos peligrosos (TGS↔TGN, Mastellone→cualquiera).
"""
import openpyxl
import pytest

from core.infrastructure import ons_ratings


HEADER = ["ENTIDAD", "FECHA", "PAIS", "AREA", "SECTOR", "TIPO DE CALIFICACIÓN",
          "CALIFICACIÓN CORTO PLAZO", "CALIFICACIÓN LARGO PLAZO",
          "PERSPECTIVA / RATING WATCH", "ESTADO"]


def _write_xlsx(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    wb.save(path)


@pytest.fixture
def ratings_file(tmp_path, monkeypatch):
    """Apunta el módulo a un xlsx temporal y resetea su cache."""
    p = tmp_path / "fixscr.xlsx"
    rows = [
        # entidad, fecha, pais, area, sector, tipo, cp, lp, persp, estado
        ["YPF S.A.", "2026-05-05", "Argentina", "FC", "Energia", "Emisor", "A1(arg)", "AAA(arg)", "Perspectiva Estable", "Confirma"],
        ["Transportadora de Gas del Norte S.A. (TGN)", "2026-05-05", "Argentina", "FC", "Energia", "Emisor", None, "AA-(arg)", "Estable", "Confirma"],
        ["Telecom Argentina S.A.", "2026-05-05", "Argentina", "FC", "Telco", "Emisor", None, "AA+(arg)", "Positiva", "Confirma"],
        ["Ledesma S.A.A.I.", "2026-06-03", "Argentina", "FC", "Agro", "Emisor", None, "AA-(arg)", "Estable", "Confirma"],
        # entidad sólo con filas por instrumento (sin fila Emisor): moda de LP
        ["SCC Power San Pedro S.A. (Ex SPI Energy S.A)", "2026-04-01", "Argentina", "FC", "Energia",
         "ON Clase IV Por ...", None, "A-(arg)", "N.C", "Confirma"],
        # ruido: una administradora de FCI homónima que NO debe matchear a un banco
        ["Patagonia Inversora S.A. Sociedad Gerente de FCI", "2026-01-01", "Argentina", "FCI", "x",
         "FCI", None, "AAf(arg)", "", "Confirma"],
    ]
    _write_xlsx(p, rows)
    monkeypatch.setattr(ons_ratings, "_XLSX_PATH", p)
    monkeypatch.setattr(ons_ratings, "_cache_mtime", None)
    monkeypatch.setattr(ons_ratings, "_fix_index", [])
    monkeypatch.setattr(ons_ratings, "_short_cache", {})
    return p


def test_exact_match_strips_legal_form(ratings_file):
    r = ons_ratings.get_rating("YPF SA")
    assert r is not None and r["rating"] == "AAA(arg)"
    assert r["perspectiva"] == "Perspectiva Estable"
    assert r["source"] == "FIXscr"


def test_alias_partial_name(ratings_file):
    # "Telecom" (sin "Argentina") resuelve vía alias.
    assert ons_ratings.get_rating("Telecom")["rating"] == "AA+(arg)"
    # variante con forma jurídica completa también.
    assert ons_ratings.get_rating("TELECOM ARGENTINA SA")["rating"] == "AA+(arg)"


def test_ledesma_alias(ratings_file):
    assert ons_ratings.get_rating("LEDESMA SAAI")["rating"] == "AA-(arg)"


def test_instrument_level_mode_fallback(ratings_file):
    # Sin fila "Emisor": toma la moda de las filas por instrumento.
    assert ons_ratings.get_rating("SCC Power San Pedro SA")["rating"] == "A-(arg)"


def test_tgs_not_matched_to_tgn(ratings_file):
    # CRÍTICO: TGS (del Sur) NO debe heredar el rating de TGN (del Norte).
    assert ons_ratings.get_rating("Transportadora de Gas del Sur S.A. (TGS)") is None


def test_blocklisted_issuer_returns_none(ratings_file):
    assert ons_ratings.get_rating("Mastellone Hnos. S.A.") is None
    assert ons_ratings.get_rating("BANCO PATAGONIA SA") is None  # no confundir con FCI homónimo


def test_unknown_issuer_returns_none(ratings_file):
    assert ons_ratings.get_rating("Emisor Inexistente S.A.") is None
    assert ons_ratings.get_rating("") is None
    assert ons_ratings.get_rating(None) is None
