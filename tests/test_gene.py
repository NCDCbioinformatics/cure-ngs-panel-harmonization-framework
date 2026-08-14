from pathlib import Path

from cure_ngs.gene import GeneCatalog


def _catalog(tmp_path: Path) -> GeneCatalog:
    gtf = tmp_path / "genes.gtf"
    gtf.write_text(
        "##gtf-version 3\n"
        '1\ttest\tgene\t1\t100\t.\t+\t.\tgene_id "ENSG1"; gene_name "TP53";\n'
        '1\ttest\tgene\t101\t200\t.\t+\t.\tgene_id "ENSG2"; gene_name "BRAF";\n'
        '1\ttest\tgene\t201\t300\t.\t+\t.\tgene_id "ENSG3"; gene_name "EML4";\n'
        '1\ttest\tgene\t301\t400\t.\t+\t.\tgene_id "ENSG4"; gene_name "ALK";\n'
        '1\ttest\tgene\t401\t500\t.\t+\t.\tgene_id "ENSG5"; gene_name "HLA-DRA";\n'
        '1\ttest\tgene\t501\t600\t.\t+\t.\tgene_id "ENSG6"; gene_name "GENEA";\n'
        '1\ttest\tgene\t601\t700\t.\t+\t.\tgene_id "ENSG7"; gene_name "GENEB";\n'
        '1\ttest\tgene\t701\t800\t.\t+\t.\tgene_id "ENSG8"; gene_name "A";\n'
        '1\ttest\tgene\t801\t900\t.\t+\t.\tgene_id "ENSG9"; gene_name "B-C";\n'
        '1\ttest\tgene\t901\t1000\t.\t+\t.\tgene_id "ENSG10"; gene_name "A-B";\n'
        '1\ttest\tgene\t1001\t1100\t.\t+\t.\tgene_id "ENSG11"; gene_name "C";\n',
        encoding="utf-8",
    )
    hgnc = tmp_path / "hgnc.tsv"
    hgnc.write_text(
        "symbol\talias_symbol\tprev_symbol\n"
        "TP53\tP53|TRP53\t\n"
        "BRAF\tRAFB\t\n"
        "EML4\t\t\n"
        "ALK\t\t\n"
        "HLA-DRA\t\t\n"
        "GENEA\tSHARED\t\n"
        "GENEB\tSHARED|BRAF\t\n"
        "A\t\t\n"
        "B-C\t\t\n"
        "A-B\t\t\n"
        "C\t\t\n",
        encoding="utf-8",
    )
    return GeneCatalog.from_files(gtf=gtf, hgnc=hgnc)


def test_gene_resolution_is_exact_by_default_and_alias_aware(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    exact = catalog.resolve("braf")
    assert exact.matched_symbol == "BRAF"
    assert exact.match_type == "name-exact"
    assert exact.ensembl_gene_ids == ("ENSG2",)

    synonym = catalog.resolve("P53")
    assert synonym.matched_symbol == "TP53"
    assert synonym.match_type == "synonym-exact"

    assert catalog.resolve("TP5").match_type == "unmatched"


def test_gene_resolution_never_silently_selects_ambiguous_alias(tmp_path: Path) -> None:
    result = _catalog(tmp_path).resolve("SHARED")

    assert result.match_type == "ambiguous-alias"
    assert result.matched_symbol is None
    assert result.candidates == ("GENEA", "GENEB")


def test_fuzzy_matching_is_opt_in_and_reports_ambiguity(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    fuzzy = catalog.resolve("BRAFF", fuzzy=True, cutoff=0.8)
    assert fuzzy.matched_symbol == "BRAF"
    assert fuzzy.match_type == "fuzzy-name"

    ambiguous = catalog.resolve(
        "GENEC", fuzzy=True, cutoff=0.75, ambiguity_delta=0.05
    )
    assert ambiguous.match_type == "ambiguous-fuzzy"
    assert set(ambiguous.candidates) >= {"GENEA", "GENEB"}
