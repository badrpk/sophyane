from pathlib import Path
from types import SimpleNamespace

import sophyane.browser_partial_recovery as recovery


def rendered():
    return SimpleNamespace(
        images=10,
        broken_images=0,
        console_errors=0,
        log_errors=0,
        horizontal_overflow=False,
    )


def run_judge(monkeypatch, tmp_path, response):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x" * 2000)

    prompts = []

    def fake_ask(prompt, screenshot):
        prompts.append(prompt)
        return response

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        recovery,
        "_nifdu_multimodal_ask",
        fake_ask,
    )

    return prompts, recovery._nifdu_visual_judge(
        original_request=(
            "make a premium dogs website with professional photography"
        ),
        html="<html><body>dogs</body></html>",
        screenshot=shot,
        rendered=rendered(),
        iteration=1,
        progress=lambda _: None,
    )


def test_prompt_contains_authoritative_render_facts(
    monkeypatch,
    tmp_path,
):
    prompts, result = run_judge(
        monkeypatch,
        tmp_path,
        (
            '{"accepted":false,"score":90,"critical_issues":0,'
            '"unmet_requirements":1,'
            '"repair_code":"VISUAL_HIERARCHY"}'
        ),
    )

    prompt = prompts[0]

    assert "broken_images" in prompt
    assert "'broken_images': 0" in prompt
    assert "Do NOT diagnose BROKEN_IMAGES" in prompt
    assert "STALE_RENDER_EVIDENCE" in prompt
    assert result["repair_code"] == "VISUAL_HIERARCHY"


def test_stale_render_code_is_not_valid_visual_verdict(
    monkeypatch,
    tmp_path,
):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x" * 2000)

    responses = iter([
        (
            '{"accepted":false,"score":62,"critical_issues":1,'
            '"unmet_requirements":1,'
            '"repair_code":"STALE_RENDER_EVIDENCE"}'
        ),
        (
            '{"accepted":false,"score":88,"critical_issues":0,'
            '"unmet_requirements":1,'
            '"repair_code":"VISUAL_HIERARCHY"}'
        ),
        (
            '{"problems":["The visual hierarchy needs targeted improvement"],'
            '"repair_instruction":"Preserve working functionality and fix only '
            'the listed visual hierarchy deficiency.",'
            '"summary":"Targeted visual hierarchy repair required."}'
        ),
    ])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        recovery,
        "_nifdu_multimodal_ask",
        lambda prompt, screenshot: next(responses),
    )

    result = recovery._nifdu_visual_judge(
        original_request="make a premium dogs website",
        html="<html><body>dogs</body></html>",
        screenshot=shot,
        rendered=rendered(),
        iteration=1,
        progress=lambda _: None,
    )

    assert result["score"] == 88
    assert result["repair_code"] == "VISUAL_HIERARCHY"


def test_broken_images_code_is_not_valid_visual_verdict(
    monkeypatch,
    tmp_path,
):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x" * 2000)

    responses = iter([
        (
            '{"accepted":false,"score":70,"critical_issues":1,'
            '"unmet_requirements":1,'
            '"repair_code":"BROKEN_IMAGES"}'
        ),
        (
            '{"accepted":false,"score":91,"critical_issues":0,'
            '"unmet_requirements":1,'
            '"repair_code":"RESPONSIVE_LAYOUT"}'
        ),
        (
            '{"problems":["The responsive layout needs targeted improvement"],'
            '"repair_instruction":"Preserve working functionality and fix only '
            'the listed responsive-layout deficiency.",'
            '"summary":"Targeted responsive repair required."}'
        ),
    ])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        recovery,
        "_nifdu_multimodal_ask",
        lambda prompt, screenshot: next(responses),
    )

    result = recovery._nifdu_visual_judge(
        original_request="make a dogs website",
        html="<html><body>dogs</body></html>",
        screenshot=shot,
        rendered=rendered(),
        iteration=1,
        progress=lambda _: None,
    )

    assert result["score"] == 91
    assert result["repair_code"] == "RESPONSIVE_LAYOUT"
