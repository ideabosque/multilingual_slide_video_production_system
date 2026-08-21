from multilingual_slide_video_agent.slides.design_system import build_css_custom_properties


def test_css_custom_properties_include_core_tokens():
    css = build_css_custom_properties()
    assert css.startswith(":root {")
    assert css.rstrip().endswith("}")
    assert "--ds-color-brand-primary: #0F4D4A;" in css
    assert "--ds-font-sans: Inter" in css
    assert "--ds-motion-duration-base-ms: 160ms;" in css
    assert "--ds-motion-slide-enter-ms: 480ms;" in css


def test_css_custom_properties_is_deterministic():
    assert build_css_custom_properties() == build_css_custom_properties()
