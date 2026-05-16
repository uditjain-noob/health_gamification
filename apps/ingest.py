from pydantic import BaseModel
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
    # Parse first, create patient only on success
    if file_path is not None:
        normalized = parser.parse_pdf(file_path)
        source = file_path
    elif data is not None:
        normalized = parser.parse_json(data)
        source = "json_upload"
    else:
        return "Error: provide file_path or data"

    if patient_id is None:
        patient_id = store.create_patient(name=patient_name)

    # Assign organs and annotate
    for item in normalized:
        item["organ"] = mapper.get_organ(item["name"])
        item.setdefault("raw_name", item["name"])

    store.save_report(patient_id=patient_id, source_file=source, parameters=normalized)
    store.log_xp(patient_id=patient_id, event="upload_report", xp=50)

    organ_counts: dict[str, int] = {}
    for item in normalized:
        organ_counts[item["organ"]] = organ_counts.get(item["organ"], 0) + 1

    breakdown = ", ".join(f"{v} {k}" for k, v in sorted(organ_counts.items()) if k != "other")
    return (
        f"Report ingested. patient_id={patient_id} | "
        f"{len(normalized)} parameters ({breakdown}) | +50 XP awarded"
    )


class UploadReportInput(BaseModel):
    patient_id: str | None = None
    patient_name: str | None = None
    file_path: str | None = None
    data: list[dict] | None = None


def register(mcp, get_store, get_parser, get_mapper):
    @mcp.tool()
    def upload_report(input: UploadReportInput) -> str:
        """
        Ingest a lab report for a patient and store all parameters with their reference ranges.

        Call this FIRST before any other tool — no data exists until a report is uploaded.
        Creates a new patient record if patient_id is omitted (returns the new patient_id in the response).
        Subsequent uploads for the same patient accumulate readings — existing parameters are updated, not duplicated.

        Parameters:
        - patient_id: omit on first upload; required for all subsequent uploads
        - patient_name: required only on first upload (used to create the patient record)
        - file_path: absolute path to a PDF lab report on disk
        - data: pre-parsed list of parameter dicts (use instead of file_path for JSON input)

        Provide exactly one of file_path or data. Returns a confirmation string with patient_id and parameter count.
        """
        return ingest_report(
            store=get_store(), parser=get_parser(), mapper=get_mapper(),
            patient_id=input.patient_id, patient_name=input.patient_name,
            file_path=input.file_path, data=input.data,
        )
