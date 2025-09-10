# services/finadvisor.py
from __future__ import annotations

import csv
import io
import re
from typing import BinaryIO, Iterable

try:
    import openpyxl  # opcional, só para XLSX
except Exception:
    openpyxl = None


# ---- Helpers -----------------------------------------------------------------

def _norm_header(s: str) -> str:
    """Normaliza cabeçalhos: remove acentuação/pontuação e baixa o texto."""
    import unicodedata
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _to_float_or_none(x):
    if x is None or x == "":
        return None
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        s = s.replace(".", "").replace(",", ".")  # pt-BR -> float
        return float(s)
    except Exception:
        return None

def _digits_only(s: str) -> str:
    if not s:
        return ""
    return "".join(re.findall(r"\d+", str(s)))


# ---- Mapeamento de cabeçalhos -> chaves internas -----------------------------

HEADER_MAP = {
    # código do cliente (1ª coluna do CSV real)
    "cod cliente": "cliente_codigo",
    "codigo cliente": "cliente_codigo",
    "codigo do cliente": "cliente_codigo",
    "codigo": "cliente_codigo",

    "origem": "origem",
    "familia": "familia",
    "produto categoria": "produto",
    "produto": "produto",
    "detalhe": "detalhe",

    "valor bruto": "valor_bruto",
    "imposto": "imposto_pct",
    "imposto pct": "imposto_pct",
    "valor liquido": "valor_liquido",

    "comissao bruta": "comissao_bruta",
    "comis bruta": "comissao_bruta",
    "comissao liquida": "comissao_liquida",
    "comis liquida": "comissao_liquida",
    "comissao escritorio r": "comissao_escritorio",
    "comis escritorio r": "comissao_escritorio",

    # colunas presentes no CSV mas que não existem na tabela:
    "comissao": None,
    "comissao pct": None,
    "comissao percent": None,
    "valor desc finder": None,
}

TABLE_COLS = {
    "data_ref",
    "cliente_codigo",
    "origem",
    "familia",
    "produto",
    "detalhe",
    "valor_bruto",
    "imposto_pct",
    "valor_liquido",
    "comissao_bruta",
    "comissao_liquida",
    "comissao_escritorio",
}


def _sanitize_row(raw: dict, data_ref: str) -> dict:
    """Converte linha crua para o formato da tabela."""
    out = {"data_ref": (data_ref or "").strip()}

    for k in ("origem", "familia", "produto", "detalhe"):
        out[k] = (str(raw.get(k)).strip() if raw.get(k) is not None else None)

    for k in ("valor_bruto", "imposto_pct", "valor_liquido",
              "comissao_bruta", "comissao_liquida", "comissao_escritorio"):
        out[k] = _to_float_or_none(raw.get(k))

    # cliente_codigo (apenas dígitos) — se vazio -> None
    code = _digits_only(raw.get("cliente_codigo"))
    out["cliente_codigo"] = code or None
    return out


# ---- Leitura CSV -------------------------------------------------------------

def _read_csv_rows(f: BinaryIO | io.TextIOBase) -> tuple[list[str], Iterable[list[str]]]:
    data = f.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")

    # detecta delimitador comum
    try:
        dialect = csv.Sniffer().sniff(data[:10000], delimiters=[",", ";", "\t"])
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    reader = csv.reader(io.StringIO(data), delimiter=delimiter, quotechar='"')
    rows = list(reader)
    if not rows:
        return [], []
    headers = rows[0]
    return headers, rows[1:]


# ---- Leitura XLSX -----------------------------------------------------------

def _read_xlsx_rows(f: BinaryIO) -> tuple[list[str], Iterable[list[str]]]:
    if openpyxl is None:
        raise RuntimeError("Leitura de XLSX requer openpyxl instalado.")
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb.active
    first = True
    headers: list[str] = []
    def gen():
        nonlocal first, headers
        for row in ws.iter_rows(values_only=True):
            vals = ["" if v is None else str(v) for v in row]
            if first:
                headers = vals
                first = False
            else:
                yield vals
    return headers, gen()


# ---- Função principal --------------------------------------------------------

def parse_finadvisor_file(file_storage, data_ref: str) -> list[dict]:
    """
    Retorna lista de linhas já com as colunas da tabela:
    {data_ref, cliente_codigo, origem, familia, produto, detalhe,
     valor_bruto, imposto_pct, valor_liquido, comissao_bruta,
     comissao_liquida, comissao_escritorio}
    """
    filename = (getattr(file_storage, "filename", "") or "").lower()
    is_csv = filename.endswith(".csv")

    if is_csv:
        headers, it = _read_csv_rows(file_storage.stream if hasattr(file_storage, "stream") else file_storage)
    else:
        headers, it = _read_xlsx_rows(file_storage.stream if hasattr(file_storage, "stream") else file_storage)

    norm_headers = [_norm_header(h) for h in headers]
    key_map: list[str | None] = [HEADER_MAP.get(nh, None) for nh in norm_headers]

    out_rows: list[dict] = []
    for row in it:
        base: dict[str, str] = {}
        for idx, val in enumerate(row[:len(key_map)]):
            target = key_map[idx]
            if target is None:
                continue
            sval = (val or "").replace("\xa0", " ").strip()
            base[target] = sval

        clean = _sanitize_row(base, data_ref)
        out_rows.append(clean)

    return out_rows
