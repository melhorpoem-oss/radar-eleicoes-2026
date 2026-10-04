#!/usr/bin/env python3
"""Build the public pre-election candidate list from the TSE's 2026 open-data archive."""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SOURCE_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip"
OUTPUT = Path("candidates-2026.json")
PHOTO_DIR = Path("candidate-photos")
PHOTO_BASE_URL = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/fotos"
STATES = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SE","SP","TO"}

OFFICE_BY_NAME = {
    "PRESIDENTE": ("president", "BR"),
    "GOVERNADOR": ("governor", None),
    "SENADOR": ("senator", None),
    "DEPUTADO FEDERAL": ("deputy_federal", None),
    "DEPUTADO ESTADUAL": ("deputy_state", None),
    "DEPUTADO DISTRITAL": ("deputy_state", None),
}

def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())

def normalized_office(row: dict[str, str]) -> tuple[str, str] | None:
    office_text = clean(row.get("DS_CARGO")).upper()
    if office_text in OFFICE_BY_NAME:
        office, fixed_state = OFFICE_BY_NAME[office_text]
        state = fixed_state or clean(row.get("SG_UE")).upper()
        return office, state

    # Fallback for future TSE layout changes: use the numeric cargo code when available.
    code = clean(row.get("CD_CARGO")).upper()
    code_map = {
        "1": "president",
        "3": "governor",
        "5": "senator",
        "6": "deputy_federal",
        "7": "deputy_state",
        "8": "deputy_state",
    }
    if code in code_map:
        office = code_map[code]
        return office, "BR" if office == "president" else clean(row.get("SG_UE")).upper()
    return None

def eligible(row: dict[str, str]) -> bool:
    status = clean(row.get("DS_SITUACAO_CANDIDATURA")).upper()
    # Keep registered/contestable candidates; exclude only statuses that mean the candidacy
    # is no longer part of the ballot universe.
    return not any(term in status for term in ("INDEFERID", "INAPTO", "CANCELAD", "RENUNCI", "FALECID"))

def add_candidate_photos(candidates: list[dict[str, str]]) -> None:
    """Cache official TSE JPEGs locally so candidate cards render before vote counting."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    (PHOTO_DIR / ".keep").touch(exist_ok=True)
    grouped: dict[str, list[dict[str, str]]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate["state"], []).append(candidate)

    for region, region_candidates in grouped.items():
        pending = [c for c in region_candidates if not (PHOTO_DIR / f'{c["id"]}.jpeg').exists()]
        if not pending:
            continue
        url = f"{PHOTO_BASE_URL}/foto_cand2026_{region}_div.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "RadarEleicoes2026/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                archive_bytes = response.read()
            pending_by_id = {c["id"]: c for c in pending}
            found: set[str] = set()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                image_files = [
                    info for info in archive.infolist()
                    if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg"}
                ]
                for info in image_files:
                    file_digits = re.sub(r"\D", "", PurePosixPath(info.filename).stem)
                    candidate_id = next((cid for cid in pending_by_id if cid in file_digits), None)
                    if candidate_id:
                        (PHOTO_DIR / f"{candidate_id}.jpeg").write_bytes(archive.read(info))
                        found.add(candidate_id)
            print(f"{region}: {len(found)}/{len(pending)} fotos encontradas no arquivo oficial.")
        except Exception as error:
            print(f"Aviso: não foi possível baixar fotos da região {region}: {error}")

    for candidate in candidates:
        image_path = PHOTO_DIR / f'{candidate["id"]}.jpeg'
        candidate["photo"] = f"./candidate-photos/{candidate['id']}.jpeg" if image_path.exists() else ""

def main() -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "RadarEleicoes2026/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        archive_bytes = response.read()

    candidates: dict[tuple[str, str, str], dict[str, str]] = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_files:
            raise RuntimeError("O arquivo do TSE não contém CSVs.")

        for name in csv_files:
            with archive.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                reader = csv.DictReader(text, delimiter=";")
                for row in reader:
                    office_info = normalized_office(row)
                    if not office_info:
                        continue
                    office, state = office_info
                    if office != "president" and state not in STATES:
                        continue
                    candidate_id = clean(row.get("SQ_CANDIDATO"))
                    display_name = clean(row.get("NM_URNA_CANDIDATO"))
                    if not candidate_id or not display_name or not eligible(row):
                        continue

                    item = {
                        "id": candidate_id,
                        "office": office,
                        "state": state,
                        "name": display_name,
                        "number": clean(row.get("NR_CANDIDATO")),
                        "party": clean(row.get("SG_PARTIDO")),
                        "situation": clean(row.get("DS_SITUACAO_CANDIDATURA")),
                        "photo": "",
                    }
                    candidates[(office, state, candidate_id)] = item

    if not candidates:
        raise RuntimeError("Nenhuma candidatura elegível foi encontrada; arquivo antigo preservado.")

    add_candidate_photos(list(candidates.values()))

    counts = {}
    for candidate in candidates.values():
        counts[candidate["office"]] = counts.get(candidate["office"], 0) + 1
    required = {"president", "governor", "senator", "deputy_federal", "deputy_state"}
    missing = required - counts.keys()
    if missing:
        raise RuntimeError(f"Arquivo do TSE sem cargos esperados: {', '.join(sorted(missing))}")

    payload = {
        "source": "Tribunal Superior Eleitoral — Dados Abertos, Candidatos 2026",
        "sourceUrl": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "candidates": sorted(
            candidates.values(),
            key=lambda item: (item["office"], item["state"], int(item["number"] or 0), item["name"]),
        ),
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    print("Candidaturas publicadas por cargo:", counts)

if __name__ == "__main__":
    main()
