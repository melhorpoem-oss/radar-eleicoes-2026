#!/usr/bin/env python3
"""Build the public poll candidate list from the TSE's 2026 open-data archive."""
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
STATES = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def add_candidate_photos(candidates: list[dict[str, str]]) -> None:
    """Cache official TSE candidate JPEGs for the poll on the same GitHub Pages origin."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    (PHOTO_DIR / ".keep").touch(exist_ok=True)
    grouped: dict[str, list[dict[str, str]]] = {}
    # Cache photos only for presidential and governor candidates to keep GitHub Pages lightweight.
    for candidate in candidates:
        if candidate["office"] in {"president", "governor"}:
            grouped.setdefault(candidate["state"], []).append(candidate)

    for region, region_candidates in grouped.items():
        pending = [candidate for candidate in region_candidates
                   if not (PHOTO_DIR / f'{candidate["id"]}.jpeg').exists()]
        if pending:
            url = f"{PHOTO_BASE_URL}/foto_cand2026_{region}_div.zip"
            request = urllib.request.Request(url, headers={"User-Agent": "RadarEleicoes2026/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=240) as response:
                    archive_bytes = response.read()
                pending_by_id = {candidate["id"]: candidate for candidate in pending}
                found: set[str] = set()
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                    image_files = [info for info in archive.infolist()
                                   if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg"}]
                    for info in image_files:
                        file_digits = re.sub(r"\\D", "", PurePosixPath(info.filename).stem)
                        candidate_id = next((candidate_id for candidate_id in pending_by_id
                                             if candidate_id in file_digits), None)
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
                    office_text = clean(row.get("DS_CARGO")).upper()
                    state_code = clean(row.get("SG_UE")).upper()
                    if office_text == "PRESIDENTE":
                        office, state = "president", "BR"
                    elif office_text == "GOVERNADOR":
                        office, state = "governor", state_code
                    elif office_text == "SENADOR":
                        office, state = "senator", state_code
                    elif office_text == "DEPUTADO FEDERAL":
                        office, state = "deputy_federal", state_code
                    elif office_text in {"DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"}:
                        office, state = "deputy_state", state_code
                    else:
                        continue
                    if office != "president" and state not in STATES:
                        continue

                    candidate_id = clean(row.get("SQ_CANDIDATO"))
                    display_name = clean(row.get("NM_URNA_CANDIDATO"))
                    if not candidate_id or not display_name:
                        continue
                    status = clean(row.get("DS_SITUACAO_CANDIDATURA"))
                    status_key = status.upper()
                    if any(term in status_key for term in ("INDEFERID", "INAPTO", "CANCELAD", "RENUNCI", "FALECID")):
                        continue
                    item = {
                        "id": candidate_id,
                        "office": office,
                        "state": state,
                        "name": display_name,
                        "number": clean(row.get("NR_CANDIDATO")),
                        "party": clean(row.get("SG_PARTIDO")),
                        "situation": status,
                        "photo": "",
                    }
                    candidates[(office, state, candidate_id)] = item

    if not candidates:
        raise RuntimeError("Nenhuma candidatura elegível foi encontrada; arquivo antigo preservado.")
    add_candidate_photos(list(candidates.values()))
    payload = {
        "source": "Tribunal Superior Eleitoral — Dados Abertos, Candidatos 2026 (Presidente, Governador, Senador e Deputados)",
        "sourceUrl": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "candidates": sorted(candidates.values(), key=lambda item: (item["office"], item["state"], int(item["number"] or 0), item["name"])),
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    print(f"Publicado arquivo com {len(candidates)} candidaturas de presidente e governador.")


if __name__ == "__main__":
    main()
