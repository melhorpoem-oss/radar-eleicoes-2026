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
from pathlib import Path

SOURCE_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip"
OUTPUT = Path("candidates-2026.json")
STATES = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


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
                    if office_text == "PRESIDENTE":
                        office, state = "president", "BR"
                    elif office_text == "GOVERNADOR":
                        office, state = "governor", clean(row.get("SG_UE")).upper()
                        if state not in STATES:
                            continue
                    else:
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
        raise RuntimeError("Nenhuma candidatura presidencial ou a governador foi encontrada; arquivo antigo preservado.")
    payload = {
        "source": "Tribunal Superior Eleitoral — Dados Abertos, Candidatos 2026",
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
