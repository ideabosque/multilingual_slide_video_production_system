from multilingual_slide_video_agent import schemas


def _segment(**overrides):
    seg = {
        "slide_index": 1,
        "slide_id": "slide_001",
        "slide_description": "intro",
        "narration": "Hello there, welcome to the deck.",
        "caption": "Welcome",
        "slide_translations": [{"node_id": "slide_001#n0", "text": "Welcome"}],
    }
    seg.update(overrides)
    return seg


def _doc(**overrides):
    doc = {"language": "en-US", "run_id": "r1", "title": "Deck Title", "segments": [_segment()]}
    doc.update(overrides)
    return doc


def test_validate_localization_accepts_well_formed_doc():
    result = schemas.validate_localization(_doc(), language="en-US")
    assert result.ok, result.errors


def test_validate_localization_flags_missing_title():
    doc = _doc(title="")
    result = schemas.validate_localization(doc, language="en-US")
    assert not result.ok
    assert any("title" in e for e in result.errors)


def test_validate_localization_flags_empty_narration():
    doc = _doc(segments=[_segment(narration="")])
    result = schemas.validate_localization(doc, language="en-US")
    assert not result.ok
    assert any("narration is empty" in e for e in result.errors)


def test_validate_localization_flags_duplicate_slide_index():
    doc = _doc(segments=[_segment(), _segment(slide_id="slide_002")])
    result = schemas.validate_localization(doc, language="en-US")
    assert not result.ok
    assert any("duplicate slide_index" in e for e in result.errors)


def test_validate_localization_language_mismatch():
    doc = _doc(language="ja-JP")
    result = schemas.validate_localization(doc, language="en-US")
    assert not result.ok


def test_validate_localization_warns_on_overlong_caption():
    doc = _doc(segments=[_segment(caption="x" * 120)])
    result = schemas.validate_localization(doc, language="en-US", caption_soft_limit=90)
    assert result.ok  # warning, not an error
    assert any("caption is 120 chars" in w for w in result.warnings)


def test_validate_localization_warns_when_caption_duplicates_narration():
    doc = _doc(segments=[_segment(narration="Same text here.", caption="Same text here.")])
    result = schemas.validate_localization(doc, language="en-US")
    assert result.ok  # warning, not an error
    assert any("identical to narration" in w for w in result.warnings)


def test_validate_localization_flags_duplicate_node_id():
    doc = _doc(segments=[_segment(slide_translations=[
        {"node_id": "slide_001#n0", "text": "a"},
        {"node_id": "slide_001#n0", "text": "b"},
    ])])
    result = schemas.validate_localization(doc, language="en-US")
    assert not result.ok
    assert any("duplicate node_id" in e for e in result.errors)


def test_validate_node_coverage_flags_missing_and_extra_nodes():
    manifest = {
        "slides": [
            {"slide_id": "slide_001", "nodes": [{"node_id": "slide_001#n0"}, {"node_id": "slide_001#n1"}]},
        ]
    }
    localization = _doc(segments=[_segment(slide_translations=[
        {"node_id": "slide_001#n0", "text": "a"},
        {"node_id": "slide_001#nZZ", "text": "b"},
    ])])
    result = schemas.validate_node_coverage(localization, manifest)
    assert not result.ok
    assert any("missing a translation" in e for e in result.errors)
    assert any("unknown node_id" in e for e in result.errors)


def test_validate_publication_metadata_title_length():
    doc = {"language": "en-US", "title": "x" * 101, "description": "d", "privacy_status": "unlisted"}
    result = schemas.validate_publication_metadata(doc)
    assert not result.ok
    assert any("100-character" in e for e in result.errors)
