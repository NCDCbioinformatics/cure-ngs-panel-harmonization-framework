from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .fasta import FastaReference
from .hgvs import normalize_hgvs
from .models import Assembly
from .table_io import read_table, write_table


MINIMAL_MAF_HEADER = (
    "Hugo_Symbol",
    "Tumor_Sample_Barcode",
    "Chromosome",
    "Start_Position",
    "End_Position",
    "Reference_Allele",
    "Tumor_Seq_Allele2",
    "Reference_Assembly",
    "HGVS_Input",
)

FAILURE_HEADER = (
    "row_index",
    "sample_id",
    "gene",
    "HGVSc",
    "HGVSp",
    "HGVSp_short",
    "hgvs_built",
    "reason",
    "detail",
)


@dataclass(frozen=True)
class HgvsTask:
    row_index: int
    sample_id: str
    gene: str
    hgvsc: object
    hgvsp: object
    hgvsp_short: object
    expression: str


@dataclass(frozen=True, order=True)
class GenomicMapping:
    chromosome: str
    start: int
    end: int
    reference: str
    alternate: str


@dataclass(frozen=True)
class HgvsToMafRun:
    status: str
    input_rows: int
    submitted_rows: int
    unique_expressions: int
    output_rows: int
    failed_rows: int
    assembly: str
    backend: str
    endpoint: str
    response_cache: str
    cache_hits: int
    fetched_responses: int
    failure_output: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _looks_like_excel_gene_date(value: object) -> bool:
    if isinstance(value, (datetime, date)):
        return True
    return bool(
        re.fullmatch(
            r"(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]00:00:00)?",
            _text(value),
        )
    )


def _build_expression(
    *, gene: str, hgvsc: object, hgvsp: object, hgvsp_short: object
) -> tuple[str | None, str]:
    nucleotide_text = _text(hgvsc)
    nucleotide_body = nucleotide_text.rsplit(":", 1)[-1].casefold()
    nucleotide_kind = "n" if nucleotide_body.startswith("n.") else "c"
    candidates = (
        (hgvsc, nucleotide_kind),
        (hgvsp, "p"),
        (hgvsp_short, "p"),
    )
    saw_value = False
    for value, kind in candidates:
        result = normalize_hgvs(value, kind=kind)
        if result.syntax_status == "missing":
            continue
        saw_value = True
        if result.syntax_status != "valid" or result.normalized is None:
            continue
        if ":" in result.normalized:
            return result.normalized, ""
        if gene:
            return f"{gene}:{result.normalized}", ""
    if not saw_value:
        return None, "NO_HGVS_STRING"
    if not gene:
        return None, "MISSING_GENE_OR_TRANSCRIPT"
    return None, "UNVALIDATED_HGVS_SYNTAX"


def _failure(
    task: HgvsTask | None,
    *,
    row_index: int,
    row: dict[str, object],
    reason: str,
    detail: str = "",
) -> dict[str, object]:
    return {
        "row_index": row_index,
        "sample_id": task.sample_id if task else _text(row.get("sample ID")),
        "gene": task.gene if task else _text(row.get("Gene")),
        "HGVSc": task.hgvsc if task else row.get("HGVSc"),
        "HGVSp": task.hgvsp if task else row.get("HGVSp"),
        "HGVSp_short": task.hgvsp_short if task else row.get("HGVSp_short"),
        "hgvs_built": task.expression if task else "",
        "reason": reason,
        "detail": detail,
    }


def prepare_hgvs_tasks(
    rows: list[dict[str, object]],
) -> tuple[list[HgvsTask], list[dict[str, object]]]:
    tasks: list[HgvsTask] = []
    failures: list[dict[str, object]] = []
    for row_index, row in enumerate(rows, start=2):
        sample_id = _text(row.get("sample ID"))
        gene = _text(row.get("Gene"))
        if not sample_id:
            failures.append(
                _failure(
                    None,
                    row_index=row_index,
                    row=row,
                    reason="MISSING_SAMPLE_ID",
                )
            )
            continue
        if _looks_like_excel_gene_date(row.get("Gene")):
            failures.append(
                _failure(
                    None,
                    row_index=row_index,
                    row=row,
                    reason="SUSPECTED_EXCEL_GENE_DATE",
                    detail=(
                        "Gene cell is date-typed; restore the approved gene symbol "
                        "from an authoritative source before conversion"
                    ),
                )
            )
            continue
        expression, reason = _build_expression(
            gene=gene,
            hgvsc=row.get("HGVSc"),
            hgvsp=row.get("HGVSp"),
            hgvsp_short=row.get("HGVSp_short"),
        )
        if expression is None:
            failures.append(
                _failure(
                    None,
                    row_index=row_index,
                    row=row,
                    reason=reason,
                )
            )
            continue
        tasks.append(
            HgvsTask(
                row_index=row_index,
                sample_id=sample_id,
                gene=gene,
                hgvsc=row.get("HGVSc"),
                hgvsp=row.get("HGVSp"),
                hgvsp_short=row.get("HGVSp_short"),
                expression=expression,
            )
        )
    return tasks, failures


def _parse_location(value: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"([^:]+):(\d+)(?:-(\d+))?(?::[-+]?\d+)?", value)
    if not match:
        raise ValueError(f"invalid VEP Location {value!r}")
    chromosome, start_value, end_value = match.groups()
    start = int(start_value)
    end = int(end_value) if end_value is not None else start
    return chromosome, start, end


def _validate_mapping(
    *,
    location: str,
    reference_allele: str,
    alternate_allele: str,
    reference: FastaReference,
) -> GenomicMapping:
    chromosome, start, end = _parse_location(location)
    contig = reference.resolve_contig(chromosome)
    ref = reference_allele.strip().upper()
    alt = alternate_allele.strip().upper()
    for field, allele in (("REF_ALLELE", ref), ("Allele", alt)):
        if allele != "-" and not re.fullmatch(r"[ACGTN]+", allele):
            raise ValueError(f"unsupported {field} {allele!r}")
    if ref == "-":
        if not alt or alt == "-":
            raise ValueError("insertion has an empty alternate allele")
        if end != start - 1:
            raise ValueError(
                "VEP insertion coordinates do not satisfy start = end + 1"
            )
        reference.fetch(contig, end, end)
    else:
        if not alt:
            raise ValueError("alternate allele is empty")
        expected_end = start + len(ref) - 1
        if end != expected_end:
            raise ValueError(
                f"coordinate span does not match REF length ({start}-{end}, {ref})"
            )
        observed = reference.fetch(contig, start, end)
        if observed != ref:
            raise ValueError(
                f"reference mismatch at {contig}:{start}-{end}: "
                f"VEP={ref}, FASTA={observed}"
            )
    return GenomicMapping(contig, start, end, ref, alt)


def parse_vep_hgvs_output(
    path: str | Path, *, reference_fasta: str | Path
) -> tuple[dict[str, set[GenomicMapping]], dict[str, list[str]]]:
    output_path = Path(path)
    reference = FastaReference(reference_fasta)
    header: list[str] | None = None
    mappings: dict[str, set[GenomicMapping]] = defaultdict(set)
    errors: dict[str, list[str]] = defaultdict(list)
    with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("##"):
                continue
            if line.startswith("#"):
                header = line[1:].rstrip("\r\n").split("\t")
                required = {"Uploaded_variation", "Location", "Allele", "REF_ALLELE"}
                missing = sorted(required - set(header))
                if missing:
                    raise ValueError(
                        f"VEP output is missing columns: {', '.join(missing)}"
                    )
                continue
            if header is None:
                raise ValueError("VEP output has data before its column header")
            values = line.rstrip("\r\n").split("\t")
            if len(values) != len(header):
                raise ValueError(
                    f"VEP output column mismatch at line {line_number}: "
                    f"expected {len(header)}, found {len(values)}"
                )
            row = dict(zip(header, values, strict=True))
            expression = row["Uploaded_variation"]
            try:
                mapping = _validate_mapping(
                    location=row["Location"],
                    reference_allele=row["REF_ALLELE"],
                    alternate_allele=row["Allele"],
                    reference=reference,
                )
            except (KeyError, ValueError) as exc:
                errors[expression].append(str(exc))
                continue
            mappings[expression].add(mapping)
    if header is None:
        raise ValueError("VEP output has no column header")
    return dict(mappings), dict(errors)


def _write_minimal_maf(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MINIMAL_MAF_HEADER,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _rest_endpoint(assembly: Assembly) -> str:
    if assembly == Assembly.GRCH37:
        return "https://grch37.rest.ensembl.org"
    return "https://rest.ensembl.org"


def _http_get(url: str, *, timeout_seconds: float) -> tuple[int, bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "cure-ngs-harmonizer/0.2.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def _cache_paths(
    cache_directory: Path, *, endpoint: str, assembly: Assembly, expression: str
) -> tuple[Path, Path, str]:
    identity = json.dumps(
        {
            "endpoint": endpoint,
            "assembly": assembly.value,
            "expression": expression,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hashlib.sha256(identity).hexdigest()
    return cache_directory / f"{key}.json", cache_directory / f"{key}.meta.json", key


def _write_cache_entry(
    raw_path: Path,
    metadata_path: Path,
    *,
    body: bytes,
    metadata: dict[str, object],
) -> None:
    raw_tmp = raw_path.with_suffix(".json.tmp")
    metadata_tmp = metadata_path.with_suffix(".json.tmp")
    raw_tmp.write_bytes(body)
    metadata_tmp.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    raw_tmp.replace(raw_path)
    metadata_tmp.replace(metadata_path)


def _load_or_fetch_rest_response(
    expression: str,
    *,
    assembly: Assembly,
    endpoint: str,
    cache_directory: Path,
    offline_replay: bool,
    retries: int,
    timeout_seconds: float,
) -> tuple[str, int | None, bytes | None, bool, str | None]:
    raw_path, metadata_path, key = _cache_paths(
        cache_directory,
        endpoint=endpoint,
        assembly=assembly,
        expression=expression,
    )
    request_url = (
        f"{endpoint}/vep/human/hgvs/{quote(expression, safe='')}"
        "?content-type=application/json"
    )
    if raw_path.is_file() and metadata_path.is_file():
        body = raw_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = hashlib.sha256(body).hexdigest()
        if metadata.get("response_sha256") != expected:
            return expression, None, None, True, "REST_CACHE_HASH_MISMATCH"
        expected_identity = {
            "cache_key": key,
            "endpoint": endpoint,
            "assembly": assembly.value,
            "expression": expression,
        }
        for field, value in expected_identity.items():
            if metadata.get(field) != value:
                return expression, None, None, True, f"REST_CACHE_{field.upper()}_MISMATCH"
        return expression, int(metadata["http_status"]), body, True, None
    if offline_replay:
        return expression, None, None, False, "REST_CACHE_MISS"

    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            status, body, headers = _http_get(
                request_url, timeout_seconds=timeout_seconds
            )
        except (OSError, URLError) as exc:
            last_error = f"REST_TRANSPORT_ERROR: {exc}"
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            return expression, None, None, False, last_error
        if status == 429 or status >= 500:
            last_error = f"REST_HTTP_{status}"
            if attempt < retries:
                retry_after = headers.get("Retry-After", "")
                delay = int(retry_after) if retry_after.isdecimal() else 2**attempt
                time.sleep(min(delay, 30))
                continue
        metadata = {
            "schema_version": "1.0",
            "cache_key": key,
            "endpoint": endpoint,
            "assembly": assembly.value,
            "expression": expression,
            "request_url": request_url,
            "http_status": status,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "response_headers": {
                key.lower(): value
                for key, value in headers.items()
                if key.lower() in {"content-type", "etag", "x-ratelimit-limit"}
            },
        }
        _write_cache_entry(
            raw_path, metadata_path, body=body, metadata=metadata
        )
        return expression, status, body, False, None
    return expression, None, None, False, last_error or "REST_REQUEST_FAILED"


def _reverse_complement(allele: str) -> str:
    if allele == "-":
        return allele
    return allele.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


def _mappings_from_rest_body(
    body: bytes,
    *,
    assembly: Assembly,
    reference_fasta: str | Path,
) -> tuple[set[GenomicMapping], list[str]]:
    reference = FastaReference(reference_fasta)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return set(), [f"invalid JSON response: {exc}"]
    if not isinstance(payload, list) or not payload:
        return set(), ["REST response is not a non-empty list"]
    mappings: set[GenomicMapping] = set()
    errors: list[str] = []
    for record_number, record in enumerate(payload, start=1):
        if not isinstance(record, dict):
            errors.append(f"record {record_number} is not an object")
            continue
        if record.get("assembly_name") != assembly.value:
            errors.append(
                f"record {record_number} assembly mismatch: "
                f"{record.get('assembly_name')!r}"
            )
            continue
        allele_string = str(record.get("allele_string") or "")
        alleles = allele_string.split("/")
        if len(alleles) < 2:
            errors.append(
                f"record {record_number} has invalid allele_string {allele_string!r}"
            )
            continue
        chromosome = str(record.get("seq_region_name") or "")
        start = record.get("start")
        end = record.get("end")
        if not chromosome or not isinstance(start, int) or not isinstance(end, int):
            errors.append(f"record {record_number} has incomplete coordinates")
            continue
        location = f"{chromosome}:{start}" if start == end else f"{chromosome}:{start}-{end}"
        strand = record.get("strand")
        for alternate in alleles[1:]:
            forward = (alleles[0].upper(), alternate.upper())
            reverse = (
                _reverse_complement(alleles[0].upper()),
                _reverse_complement(alternate.upper()),
            )
            candidates = (reverse, forward) if strand == -1 else (forward, reverse)
            candidate_errors: list[Exception] = []
            mapping = None
            for reference_allele, alternate_allele in candidates:
                try:
                    mapping = _validate_mapping(
                        location=location,
                        reference_allele=reference_allele,
                        alternate_allele=alternate_allele,
                        reference=reference,
                    )
                    break
                except (KeyError, ValueError) as exc:
                    candidate_errors.append(exc)
            if mapping is None:
                errors.append(f"record {record_number}: {candidate_errors[0]}")
            else:
                mappings.add(mapping)
    return mappings, errors


def resolve_hgvs_with_rest_cache(
    expressions: tuple[str, ...],
    *,
    assembly: Assembly,
    reference_fasta: str | Path,
    response_cache: str | Path,
    offline_replay: bool = False,
    endpoint: str | None = None,
    threads: int = 4,
    retries: int = 3,
    timeout_seconds: float = 30.0,
) -> tuple[
    dict[str, set[GenomicMapping]], dict[str, list[str]], int, int, str
]:
    if threads < 1 or threads > 16:
        raise ValueError("REST threads must be between 1 and 16")
    if retries < 0:
        raise ValueError("REST retries cannot be negative")
    if timeout_seconds <= 0:
        raise ValueError("REST timeout must be positive")
    endpoint_value = (endpoint or _rest_endpoint(assembly)).rstrip("/")
    cache_directory = Path(response_cache)
    cache_directory.mkdir(parents=True, exist_ok=True)
    mappings: dict[str, set[GenomicMapping]] = {}
    errors: dict[str, list[str]] = defaultdict(list)
    cache_hits = 0
    fetched_responses = 0

    def resolve_one(expression: str):
        return _load_or_fetch_rest_response(
            expression,
            assembly=assembly,
            endpoint=endpoint_value,
            cache_directory=cache_directory,
            offline_replay=offline_replay,
            retries=retries,
            timeout_seconds=timeout_seconds,
        )

    with ThreadPoolExecutor(max_workers=threads) as executor:
        results = list(executor.map(resolve_one, expressions))
    for expression, status, body, cache_hit, error in results:
        cache_hits += int(cache_hit)
        fetched_responses += int(not cache_hit and body is not None)
        if error:
            errors[expression].append(error)
            continue
        if status != 200 or body is None:
            errors[expression].append(f"REST_HTTP_{status}")
            continue
        expression_mappings, expression_errors = _mappings_from_rest_body(
            body,
            assembly=assembly,
            reference_fasta=reference_fasta,
        )
        mappings[expression] = expression_mappings
        errors[expression].extend(expression_errors)
    return mappings, dict(errors), cache_hits, fetched_responses, endpoint_value


def hgvs_table_to_minimal_maf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    failure_output: str | Path,
    reference_fasta: str | Path,
    assembly: Assembly,
    response_cache: str | Path,
    delimiter: str = "\t",
    sheet: str | int = 0,
    offline_replay: bool = False,
    endpoint: str | None = None,
    threads: int = 4,
    retries: int = 3,
    timeout_seconds: float = 30.0,
) -> HgvsToMafRun:
    input_path = Path(input_path)
    output_path = Path(output_path)
    failure_output = Path(failure_output)
    reference_fasta = Path(reference_fasta)
    reference = FastaReference(reference_fasta)
    del reference

    header, rows = read_table(input_path, delimiter=delimiter, sheet=sheet)
    required = {"sample ID", "Gene", "HGVSc", "HGVSp", "HGVSp_short"}
    missing = sorted(required - set(header))
    if missing:
        raise ValueError(f"HGVS input table is missing columns: {', '.join(missing)}")
    if not rows:
        raise ValueError("HGVS input table contains no data rows")
    tasks, failures = prepare_hgvs_tasks(rows)
    expressions = tuple(dict.fromkeys(task.expression for task in tasks))
    mappings, mapping_errors, cache_hits, fetched_responses, endpoint_value = (
        resolve_hgvs_with_rest_cache(
            expressions,
            assembly=assembly,
            reference_fasta=reference_fasta,
            response_cache=response_cache,
            offline_replay=offline_replay,
            endpoint=endpoint,
            threads=threads,
            retries=retries,
            timeout_seconds=timeout_seconds,
        )
    )

    output_rows: list[dict[str, object]] = []
    for task in tasks:
        task_mappings = mappings.get(task.expression, set()) if expressions else set()
        if len(task_mappings) == 1:
            mapping = next(iter(task_mappings))
            output_rows.append(
                {
                    "Hugo_Symbol": task.gene,
                    "Tumor_Sample_Barcode": task.sample_id,
                    "Chromosome": mapping.chromosome,
                    "Start_Position": mapping.start,
                    "End_Position": mapping.end,
                    "Reference_Allele": mapping.reference,
                    "Tumor_Seq_Allele2": mapping.alternate,
                    "Reference_Assembly": assembly.value,
                    "HGVS_Input": task.expression,
                }
            )
            continue
        source_row = {
            "sample ID": task.sample_id,
            "Gene": task.gene,
            "HGVSc": task.hgvsc,
            "HGVSp": task.hgvsp,
            "HGVSp_short": task.hgvsp_short,
        }
        if len(task_mappings) > 1:
            reason = "AMBIGUOUS_MULTIPLE_GENOMIC_VARIANTS"
            detail = f"{len(task_mappings)} distinct mappings"
        elif task.expression in mapping_errors:
            reason = "REST_MAPPING_VALIDATION_FAILED"
            detail = "; ".join(dict.fromkeys(mapping_errors[task.expression]))
        else:
            reason = "REST_NO_MAPPING"
            detail = ""
        failures.append(
            _failure(
                task,
                row_index=task.row_index,
                row=source_row,
                reason=reason,
                detail=detail,
            )
        )

    # Tasks are processed in input-row order, so output order remains stable even
    # when multiple samples contain the same HGVS expression.
    failures.sort(key=lambda row: int(row["row_index"]))
    _write_minimal_maf(output_path, output_rows)
    write_table(failure_output, FAILURE_HEADER, failures, delimiter="\t")

    if not output_rows:
        status = "FAILED_ALL"
    elif failures:
        status = "PARTIAL"
    else:
        status = "SUCCESS"
    return HgvsToMafRun(
        status=status,
        input_rows=len(rows),
        submitted_rows=len(tasks),
        unique_expressions=len(expressions),
        output_rows=len(output_rows),
        failed_rows=len(failures),
        assembly=assembly.value,
        backend="ensembl-rest-frozen-cache",
        endpoint=endpoint_value,
        response_cache=str(Path(response_cache).resolve()),
        cache_hits=cache_hits,
        fetched_responses=fetched_responses,
        failure_output=str(failure_output.resolve()),
    )
