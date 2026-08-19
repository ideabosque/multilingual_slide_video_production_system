from multilingual_slide_video_agent import terminology


def test_check_text_flags_missing_required_term():
    report = terminology.check_text(
        "Our new dashboard makes reporting effortless.",
        language="en-US",
        required_preserved_terms=["IdeaBosque", "API"],
    )
    assert not report.ok
    kinds = {v.kind for v in report.violations}
    assert "missing_preserved_term" in kinds


def test_check_text_passes_when_required_terms_present():
    report = terminology.check_text(
        "IdeaBosque exposes this through a simple API.",
        language="en-US",
        required_preserved_terms=["IdeaBosque", "API"],
    )
    assert report.ok, report.as_dict()


def test_check_text_flags_project_forbidden_term():
    report = terminology.check_text(
        "This deck also mentions Acme Corp.",
        language="en-US",
        project_terminology={"forbidden_terms": {"*": ["Acme Corp"]}},
    )
    assert not report.ok
    assert report.violations[0].kind == "forbidden_term"


def test_find_preserved_terms_in_text_whole_word_match():
    found = terminology.find_preserved_terms_in_text("Our SKU catalog integrates with the ERP via API.")
    assert "SKU" in found
    assert "ERP" in found
    assert "API" in found
