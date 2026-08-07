from unittest.mock import patch

from sophyane.code_memory.sli_rich_site_compose import (
    Entity,
    _render,
)
from sophyane.code_memory.sli_site_generative import (
    build_creative_brief,
    propose_design,
)
from sophyane.code_memory.sli_site_intelligence import (
    apply_design_proposal,
    build_site_plan,
    infer_site_intent,
)
from sophyane.code_memory.topic_site_compose import (
    TopicSource,
)


def source() -> TopicSource:
    return TopicSource(
        requested_topic=
            "Demis Hassabis",

        resolved_title=
            "Demis Hassabis",

        extract=(
            "Demis Hassabis is an artificial intelligence "
            "researcher and scientist. "
            "He co-founded DeepMind and worked on machine learning. "
            "DeepMind developed AlphaGo. "
            "His research contributed to AlphaFold and protein "
            "structure prediction. "
            "He received the Nobel Prize in Chemistry in 2024."
        ),

        page_url=
            "https://example.invalid/demis",

        image_data_uri=
            (
                "data:image/jpeg;base64,"
                "DEMISPRIMARY"
            ),
    )


def entities() -> list[Entity]:
    return [
        Entity(
            "DeepMind",
            "Research context. " * 8,
            "https://example.invalid/deepmind",
            None,
            "Research",
        ),
        Entity(
            "AlphaGo",
            "Research context. " * 8,
            "https://example.invalid/alphago",
            None,
            "Research",
        ),
        Entity(
            "AlphaFold",
            "Science context. " * 8,
            "https://example.invalid/alphafold",
            None,
            "Science",
        ),
    ]


def brief():
    item = source()
    related = entities()

    intent = infer_site_intent(
        item,
        related,
    )

    return build_creative_brief(
        item,
        related,
        intent,
    )


def response() -> str:
    return r'''
{
  "concept": "From Games to Proteins",
  "narrative_shape": "A progression of research systems by consequence",
  "hero_treatment": "Identity portrait with restrained scientific annotation",
  "feature_title": "Systems that crossed into science",
  "feature_intro": "Grounded milestones move from machine intelligence toward protein structure prediction.",
  "section_labels": [
    "Building Intelligence",
    "DeepMind",
    "Game Systems",
    "Protein Structure"
  ],
  "layout_strategy": "discovery-sequence",
  "interaction_concepts": [
    "research-path",
    "breakthrough-navigation"
  ],
  "visual_mood": "scientific editorial",
  "visual_rhythm": "quiet identity, dense evidence, broad consequence",
  "primary_interaction": "research-path"
}
'''


def test_valid_proposal_is_accepted() -> None:
    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            response(),
    )

    assert proposal.generated is True

    assert (
        proposal.concept
        ==
        "From Games to Proteins"
    )

    assert (
        proposal.layout_strategy
        ==
        "discovery-sequence"
    )


def test_malformed_response_falls_back() -> None:
    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            "not JSON",
    )

    assert proposal.generated is False
    assert proposal.reason


def test_unbounded_layout_falls_back() -> None:
    bad = response().replace(
        '"discovery-sequence"',
        '"arbitrary-html-generation"',
    )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            bad,
    )

    assert proposal.generated is False


def test_semantic_family_cannot_be_changed_by_proposal() -> None:
    item = source()
    related = entities()

    base = build_site_plan(
        item,
        related,
    )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            response(),
    )

    final = apply_design_proposal(
        base,
        proposal,
    )

    assert base.family == "research-profile"

    assert (
        final.family
        ==
        base.family
    )

    assert (
        final.visual_family
        ==
        base.visual_family
    )

    assert final.accent == base.accent
    assert final.accent2 == base.accent2

    assert (
        final.design_concept
        ==
        "From Games to Proteins"
    )


def test_generated_design_reaches_html() -> None:
    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            response(),
    )

    with patch(
        "sophyane.code_memory."
        "sli_rich_site_compose.propose_design",
        return_value=proposal,
    ):
        document = _render(
            source(),
            entities(),
        )

    assert (
        'data-layout-family="research-profile"'
        in document
    )

    assert (
        'data-design-generated="true"'
        in document
    )

    assert (
        'data-layout-strategy="discovery-sequence"'
        in document
    )

    assert (
        "From Games to Proteins"
        in document
    )

    hero = document.split(
        '<header class="hero">',
        1,
    )[1].split(
        "</header>",
        1,
    )[0]

    assert "DEMISPRIMARY" in hero


def test_disable_flag_preserves_deterministic_path(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "SOPHYANE_DISABLE_GENERATIVE_SITE_DESIGN",
        "1",
    )

    called = False

    def generator(
        _prompt,
    ):
        nonlocal called

        called = True

        raise AssertionError(
            "generator must not execute"
        )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=generator,
    )

    assert called is False
    assert proposal.generated is False


def test_real_local_adapter_uses_generate_with_system_prompt() -> None:
    from sophyane.code_memory import (
        sli_site_generative,
    )

    calls = []

    class FakeProvider:
        def __init__(
            self,
            **kwargs,
        ):
            calls.append(
                (
                    "init",
                    kwargs,
                )
            )

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            calls.append(
                (
                    "generate",
                    prompt,
                    system_prompt,
                )
            )

            return (
                '{"concept":"Test","narrative_shape":"shape",'
                '"hero_treatment":"portrait",'
                '"feature_title":"title",'
                '"feature_intro":"intro",'
                '"section_labels":["A","B","C","D"],'
                '"layout_strategy":"milestone-grid",'
                '"interaction_concepts":["research-path"],'
                '"visual_mood":"mood",'
                '"visual_rhythm":"rhythm",'
                '"primary_interaction":"research-path"}'
            )

    with patch(
        "sophyane.providers.local_gguf."
        "LocalGgufProvider",
        FakeProvider,
    ):
        result = (
            sli_site_generative
            ._call_local_llm(
                "DESIGN PROMPT"
            )
        )

    assert result.startswith(
        '{"concept"'
    )

    assert calls[0][0] == "init"
    assert calls[1][0] == "generate"

    assert (
        calls[1][1]
        ==
        "DESIGN PROMPT"
    )

    assert isinstance(
        calls[1][2],
        str,
    )

    assert (
        "valid JSON object"
        in calls[1][2]
    )


def test_local_adapter_retries_after_loading_model(
    monkeypatch,
) -> None:
    from sophyane.code_memory import (
        sli_site_generative,
    )

    from sophyane.providers.base import (
        ProviderError,
    )

    calls = []

    class FakeProvider:
        def __init__(
            self,
            **kwargs,
        ):
            calls.append(
                (
                    "init",
                    kwargs,
                )
            )

            self.attempts = 0

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.attempts += 1

            calls.append(
                (
                    "generate",
                    self.attempts,
                    prompt,
                    system_prompt,
                )
            )

            if self.attempts == 1:
                raise ProviderError(
                    'HTTP 503: '
                    '{"error":{"message":"Loading model"}}'
                )

            return '{"ok":true}'

    monkeypatch.setattr(
        "sophyane.providers.local_gguf."
        "LocalGgufProvider",
        FakeProvider,
    )

    monkeypatch.setattr(
        "sophyane.local_server."
        "ensure_server_background",
        lambda: (
            True,
            "llama-server is loading",
        ),
    )

    waits = []

    def fake_wait(
        timeout,
    ):
        waits.append(
            timeout
        )

        return True

    monkeypatch.setattr(
        "sophyane.local_server."
        "wait_until_ready",
        fake_wait,
    )

    monkeypatch.setattr(
        "sophyane.local_server."
        "failure_detail",
        lambda: "",
    )

    monkeypatch.setattr(
        "time.sleep",
        lambda _seconds:
            None,
    )

    result = (
        sli_site_generative
        ._call_local_llm(
            "DESIGN"
        )
    )

    assert result == '{"ok":true}'

    generate_calls = [
        item
        for item in calls
        if item[0] == "generate"
    ]

    assert len(
        generate_calls
    ) == 2

    assert waits == [
        75.0
    ]


def test_local_adapter_does_not_retry_non_loading_provider_error(
    monkeypatch,
) -> None:
    from sophyane.code_memory import (
        sli_site_generative,
    )

    from sophyane.providers.base import (
        ProviderError,
    )

    class FakeProvider:
        def __init__(
            self,
            **_kwargs,
        ):
            pass

        def generate(
            self,
            _prompt,
            _system_prompt,
        ):
            raise ProviderError(
                "permanent local inference failure"
            )

    monkeypatch.setattr(
        "sophyane.providers.local_gguf."
        "LocalGgufProvider",
        FakeProvider,
    )

    called = False

    def forbidden_start():
        nonlocal called

        called = True

        raise AssertionError(
            "server startup must not run "
            "for unrelated provider errors"
        )

    monkeypatch.setattr(
        "sophyane.local_server."
        "ensure_server_background",
        forbidden_start,
    )

    try:
        (
            sli_site_generative
            ._call_local_llm(
                "DESIGN"
            )
        )

    except ProviderError as error:
        assert (
            "permanent local inference failure"
            in str(
                error
            )
        )

    else:
        raise AssertionError(
            "ProviderError expected"
        )

    assert called is False



def test_natural_grid_layout_maps_to_bounded_research_layout() -> None:
    natural = r'''
{
  "concept": "Research Signals",
  "narrative_shape": "A sequence of grounded research milestones",
  "hero_treatment": "Identity portrait with subtle scientific annotation",
  "feature_title": "The systems behind the breakthroughs",
  "feature_intro": "Grounded research evidence is presented through major milestones.",
  "section_labels": [
    "Foundations",
    "DeepMind",
    "Game Systems",
    "Protein Structure"
  ],
  "layout_strategy": "grid layout",
  "interaction_concepts": [
    "research navigation"
  ],
  "visual_mood": "scientific editorial",
  "visual_rhythm": "structured evidence",
  "primary_interaction": "research navigation"
}
'''

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            natural,
    )

    assert proposal.generated is True

    assert (
        proposal.layout_strategy
        ==
        "milestone-grid"
    )

    assert (
        proposal.primary_interaction
        ==
        "research-path"
    )


def test_space_form_of_canonical_token_is_accepted() -> None:
    natural = response().replace(
        '"discovery-sequence"',
        '"discovery sequence"',
    ).replace(
        '"research-path"',
        '"research path"',
    )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            natural,
    )

    assert proposal.generated is True

    assert (
        proposal.layout_strategy
        ==
        "discovery-sequence"
    )

    assert (
        proposal.primary_interaction
        ==
        "research-path"
    )


def test_unknown_layout_still_rejected_after_normalisation() -> None:
    bad = response().replace(
        '"discovery-sequence"',
        '"floating holographic chaos"',
    )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=lambda _prompt:
            bad,
    )

    assert proposal.generated is False

    assert (
        proposal.layout_strategy
        ==
        "milestone-grid"
    )


def test_invalid_first_proposal_can_be_repaired_once() -> None:
    outputs = [
        r'''
{
  "concept": "DeepMind Innovator",
  "narrative_shape": "Research milestones",
  "hero_treatment": "Identity portrait",
  "feature_title": "Research systems",
  "feature_intro": "Grounded research milestones.",
  "section_labels": [
    "Research",
    "Innovation",
    "Impact",
    "Legacy"
  ],
  "layout_strategy": "floating crystalline lattice",
  "interaction_concepts": [
    "research path"
  ],
  "visual_mood": "scientific",
  "visual_rhythm": "progressive",
  "primary_interaction": "research path"
}
''',
        r'''
{
  "concept": "DeepMind Innovator",
  "narrative_shape": "Research milestones ordered by consequence",
  "hero_treatment": "Identity portrait with scientific framing",
  "feature_title": "Research systems",
  "feature_intro": "Grounded research milestones progress toward scientific consequence.",
  "section_labels": [
    "Research",
    "DeepMind",
    "Game Systems",
    "Protein Structure"
  ],
  "layout_strategy": "milestone-grid",
  "interaction_concepts": [
    "research-path"
  ],
  "visual_mood": "scientific editorial",
  "visual_rhythm": "progressive evidence bands",
  "primary_interaction": "research-path"
}
''',
    ]

    prompts = []

    def generator(
        prompt: str,
    ) -> str:
        prompts.append(
            prompt
        )

        return outputs[
            len(prompts) - 1
        ]

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=generator,
    )

    assert len(prompts) == 2

    assert proposal.generated is True

    assert (
        proposal.layout_strategy
        ==
        "milestone-grid"
    )

    assert (
        proposal.primary_interaction
        ==
        "research-path"
    )

    assert (
        "CORRECTION REQUIRED"
        in prompts[1]
    )

    assert (
        "floating crystalline lattice"
        in prompts[1]
    )


def test_two_invalid_proposals_fall_back_after_one_repair() -> None:
    calls = 0

    bad = r'''
{
  "concept": "Unbounded",
  "narrative_shape": "Invalid architecture",
  "hero_treatment": "Identity portrait",
  "feature_title": "Research",
  "feature_intro": "Grounded context.",
  "section_labels": ["A", "B", "C", "D"],
  "layout_strategy": "floating crystalline lattice",
  "interaction_concepts": [],
  "visual_mood": "experimental",
  "visual_rhythm": "chaotic",
  "primary_interaction": "research-path"
}
'''

    def generator(
        _prompt: str,
    ) -> str:
        nonlocal calls

        calls += 1

        return bad

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=generator,
    )

    assert calls == 2
    assert proposal.generated is False

    assert (
        proposal.layout_strategy
        ==
        "milestone-grid"
    )

    assert (
        "unsupported layout_strategy"
        in proposal.reason
    )


def test_provider_failure_does_not_trigger_design_retry() -> None:
    from sophyane.providers.base import (
        ProviderError,
    )

    calls = 0

    def generator(
        _prompt: str,
    ) -> str:
        nonlocal calls

        calls += 1

        raise ProviderError(
            "local inference unavailable"
        )

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=generator,
    )

    assert calls == 1
    assert proposal.generated is False

    assert (
        "local inference unavailable"
        in proposal.reason
    )


def test_repair_prompt_contains_family_allowlists() -> None:
    prompts = []

    def generator(
        prompt: str,
    ) -> str:
        prompts.append(
            prompt
        )

        if len(
            prompts
        ) == 1:
            return r'''
{
  "concept": "Test",
  "narrative_shape": "Test",
  "hero_treatment": "Identity portrait",
  "feature_title": "Test",
  "feature_intro": "Grounded research context.",
  "section_labels": ["A", "B", "C", "D"],
  "layout_strategy": "not-a-real-layout",
  "interaction_concepts": [],
  "visual_mood": "scientific",
  "visual_rhythm": "structured",
  "primary_interaction": "research-path"
}
'''

        return response()

    proposal = propose_design(
        brief(),
        lambda _message: None,
        generator=generator,
    )

    assert proposal.generated is True
    assert len(prompts) == 2

    repair = prompts[1]

    assert "milestone-grid" in repair
    assert "research-ledger" in repair
    assert "discovery-sequence" in repair
    assert "research-path" in repair
    assert "milestone-exploration" in repair
