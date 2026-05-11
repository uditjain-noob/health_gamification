from core.parser import Parser
from core.organs import OrganMapper
from db.store import Store


def ingest_report(
    store: Store,
    parser: Parser,
    mapper: OrganMapper,
    patient_id: str | None,
    patient_name: str | None,
    file_path: str | None,
    data: list[dict] | None,
) -> str:
    if patient_id is None:
        patient_id = store.create_patient(name=patient_name)

    if file_path:
        normalized = parser.parse_pdf(file_path)
        source = file_path
    elif data:
        normalized = parser.parse_json(data)
        source = "json_upload"
    else:
        return f"Error: provide file_path or data. patient_id={patient_id}"

    # Assign organs and annotate
    for item in normalized:
        item["organ"] = mapper.get_organ(item["name"])
        item.setdefault("raw_name", item["name"])

    store.save_report(patient_id=patient_id, source_file=source, parameters=normalized)
    store.log_xp(patient_id=patient_id, event="upload_report", xp=50)

    organ_counts: dict[str, int] = {}
    for item in normalized:
        organ_counts[item["organ"]] = organ_counts.get(item["organ"], 0) + 1

    breakdown = ", ".join(f"{v} {k}" for k, v in organ_counts.items() if k != "other")
    return (
        f"Report ingested. patient_id={patient_id} | "
        f"{len(normalized)} parameters ({breakdown}) | +50 XP awarded"
    )


def register(mcp, get_store, get_parser, get_mapper):
    @mcp.tool()
    def upload_report(
        patient_id: str | None = None,
        patient_name: str | None = None,
        file_path: str | None = None,
        data: list[dict] | None = None,
    ) -> str:
        """Upload a lab report (JSON list or PDF file path) for a patient."""
        return ingest_report(
            store=get_store(), parser=get_parser(), mapper=get_mapper(),
            patient_id=patient_id, patient_name=patient_name,
            file_path=file_path, data=data,
        )
