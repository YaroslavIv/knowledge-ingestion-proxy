import json

import pytest
import respx
from httpx import Response

from app.course_generation.module_generate import apply_edits, build_generate_prompt, generate_module_output
from app.owui_client import OwuiClient


def test_build_generate_prompt_revise_shape_embeds_current_html_and_instruction():
    prompt = build_generate_prompt(
        title="Module 05 — Objections",
        learning_objectives=["Handle price objections"],
        current_html="<html><body>old content</body></html>",
        instruction="Add two more practice exercises.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
    )
    assert "<html><body>old content</body></html>" in prompt
    assert "Add two more practice exercises." in prompt
    assert "REQUESTED CHANGE" in prompt
    assert '"edits"' in prompt


def test_build_generate_prompt_from_scratch_shape_embeds_objectives_and_material():
    prompt = build_generate_prompt(
        title="Module 09 — New Topic",
        learning_objectives=["Explain the new feature"],
        current_html=None,
        instruction="Focus on the roadmap angle.",
        product_files=[{"filename": "roadmap.txt", "content": "Q3 roadmap details."}],
        methodology_text="Explain -> Engage -> Check -> Apply.",
        feedback_notes=["Don't re-explain product tiers from scratch."],
    )
    assert "Explain the new feature" in prompt
    assert "roadmap.txt" in prompt
    assert "Q3 roadmap details." in prompt
    assert "Explain -> Engage -> Check -> Apply." in prompt
    assert "Don't re-explain product tiers from scratch." in prompt
    assert "Focus on the roadmap angle." in prompt


def test_build_generate_prompt_revise_always_includes_current_materials():
    """A revise must always see the collections' current content, not just
    the module's own previous HTML — otherwise it could keep citing facts
    the source material no longer has (e.g. after a cleanup) with nothing
    to ever correct that."""
    prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html="<html>old</html>",
        instruction="Change the accent color to green.",
        product_files=[{"filename": "datasheet.txt", "content": "Elite supports 1000 FPS."}],
        methodology_text="Explain -> Engage.",
        feedback_notes=[],
    )
    assert "Elite supports 1000 FPS." in prompt
    assert "Explain -> Engage." in prompt


def test_build_generate_prompt_includes_competitor_material_in_both_shapes():
    competitor_files = [{"filename": "rival.txt", "content": "Rival Corp lacks night-vision support."}]

    from_scratch_prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html=None,
        instruction="",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        competitor_files=competitor_files,
    )
    assert "Rival Corp lacks night-vision support." in from_scratch_prompt

    revise_prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html="<html>old</html>",
        instruction="Sharpen the positioning section.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        competitor_files=competitor_files,
    )
    assert "Rival Corp lacks night-vision support." in revise_prompt


def test_build_generate_prompt_includes_visual_guidance_in_both_shapes():
    visual_guidance = "Use a dark navy accent color and rounded card components."

    from_scratch_prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html=None,
        instruction="",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        visual_guidance=visual_guidance,
    )
    assert visual_guidance in from_scratch_prompt

    revise_prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html="<html>old</html>",
        instruction="Restyle the buttons.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        visual_guidance=visual_guidance,
    )
    assert visual_guidance in revise_prompt


def test_build_generate_prompt_from_scratch_includes_other_modules_and_their_content():
    prompt = build_generate_prompt(
        title="Module 09 — Final Test",
        learning_objectives=["Test what the learner retained"],
        current_html=None,
        instruction="Only quiz on what this course actually covered.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        other_modules=[{"title": "Module 01 — Intro", "learning_objectives": ["Explain the basics"]}],
        other_modules_content=[{"title": "Module 01 — Intro", "text": "Elite supports 1000 FPS."}],
    )
    assert "Module 01 — Intro" in prompt
    assert "Explain the basics" in prompt
    assert "Elite supports 1000 FPS." in prompt


def test_build_generate_prompt_revise_can_also_see_other_modules_and_their_content():
    """Revising a module can now be scoped to see sibling context too — not
    just a from-scratch generation — since content-visibility is the
    caller's explicit choice (other_module_ids), not tied to which shape of
    generation this is."""
    prompt = build_generate_prompt(
        title="Module 09 — Final Test",
        learning_objectives=[],
        current_html="<html>old quiz</html>",
        instruction="Add a question about the new pricing tier.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        other_modules=[{"title": "Module 03 — Pricing", "learning_objectives": ["Explain pricing tiers"]}],
        other_modules_content=[{"title": "Module 03 — Pricing", "text": "The Pro tier costs $99/month."}],
    )
    assert "Module 03 — Pricing" in prompt
    assert "The Pro tier costs $99/month." in prompt


def test_build_generate_prompt_from_scratch_includes_style_reference_html():
    """A from-scratch module (e.g. a final test) has no page of its own to
    inherit CSS/layout from — without a real style template, the model was
    inventing its own look, so a freshly generated module could end up
    styled nothing like the rest of the course. It must see one real
    module's actual HTML as an explicit "match this" template."""
    prompt = build_generate_prompt(
        title="Module 09 — Final Test",
        learning_objectives=["Test what the learner retained"],
        current_html=None,
        instruction="",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        style_reference_html="<html><head><style>body{color:blue}</style></head><body>Module 01</body></html>",
    )
    assert "VISUAL STYLE TEMPLATE" in prompt
    assert "body{color:blue}" in prompt


def test_build_generate_prompt_revise_can_also_receive_an_explicit_style_reference():
    """Content-visibility and style-borrowing are independent choices — a
    caller revising a module can still explicitly ask to see another
    module's HTML as a visual comparison, even though the module being
    revised already has its own current_html as a style baseline."""
    prompt = build_generate_prompt(
        title="Module 05",
        learning_objectives=[],
        current_html="<html>old</html>",
        instruction="Change the accent color to green.",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
        style_reference_html="<html><head><style>body{color:blue}</style></head><body>Other module</body></html>",
    )
    assert "VISUAL STYLE TEMPLATE" in prompt
    assert "body{color:blue}" in prompt


def test_apply_edits_inserts_before_a_unique_anchor():
    result = apply_edits(
        "<body><p>Intro</p></body>",
        [{"find": "</body>", "replace": "<p>New section</p></body>"}],
    )
    assert result == "<body><p>Intro</p><p>New section</p></body>"


def test_apply_edits_applies_multiple_edits_in_order():
    result = apply_edits(
        "one two three",
        [{"find": "one", "replace": "1"}, {"find": "three", "replace": "3"}],
    )
    assert result == "1 two 3"


def test_apply_edits_rejects_a_missing_anchor():
    with pytest.raises(ValueError, match="could not find"):
        apply_edits("<body></body>", [{"find": "<nope>", "replace": "x"}])


def test_apply_edits_rejects_an_ambiguous_anchor():
    with pytest.raises(ValueError, match="not unique"):
        apply_edits("a-a-a", [{"find": "a", "replace": "b"}])


@respx.mock
async def test_generate_module_output_strips_markdown_fences_when_generating_from_scratch():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": "```html\n<html><body>Hi</body></html>\n```"}}]},
        )
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    html = await generate_module_output(
        client,
        model="gpt-4o-mini",
        title="Module 01",
        learning_objectives=[],
        current_html=None,
        instruction="",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
    )
    assert html == "<html><body>Hi</body></html>"


@respx.mock
async def test_generate_module_output_rejects_non_html_response():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "Sorry, I can't help with that."}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(ValueError, match="did not look like an HTML document"):
        await generate_module_output(
            client,
            model="gpt-4o-mini",
            title="Module 01",
            learning_objectives=[],
            current_html=None,
            instruction="",
            product_files=[],
            methodology_text="",
            feedback_notes=[],
        )


@respx.mock
async def test_generate_module_output_rejects_a_truncated_from_scratch_response():
    """A real live test against a 161KB imported module page showed the model
    can stop generating mid-document once it hits its own output-token cap —
    silently persisting that as a "current" version would corrupt the page.
    """
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "<html><body>truncated mid-sen"}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(ValueError, match="truncated"):
        await generate_module_output(
            client,
            model="gpt-4o-mini",
            title="Module 01",
            learning_objectives=[],
            current_html=None,
            instruction="",
            product_files=[],
            methodology_text="",
            feedback_notes=[],
        )


@respx.mock
async def test_generate_module_output_revises_via_bounded_find_replace_edits():
    """The revise path must never ask the model to echo the whole document
    back — only small edits, applied locally — so it stays correct
    regardless of how large the current module page is."""
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"edits": [{"find": "</body>", "replace": "<p>New practice</p></body>"}]}
                            )
                        }
                    }
                ]
            },
        )
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    html = await generate_module_output(
        client,
        model="gpt-4o-mini",
        title="Module 01",
        learning_objectives=[],
        current_html="<body><p>Original</p></body>",
        instruction="Add a practice exercise",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
    )
    assert html == "<body><p>Original</p><p>New practice</p></body>"
    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["response_format"] == {"type": "json_object"}


@respx.mock
async def test_generate_module_output_revise_retries_once_then_succeeds():
    """A missing/ambiguous anchor gets the model one retry, fed its own
    error, before anything falls back to a full rewrite."""
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        side_effect=[
            Response(200, json={"choices": [{"message": {"content": json.dumps({"edits": [{"find": "nope", "replace": "x"}]})}}]}),
            Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"edits": [{"find": "</body>", "replace": "<p>Fixed</p></body>"}]})}}
                    ]
                },
            ),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    html = await generate_module_output(
        client,
        model="gpt-4o-mini",
        title="Module 01",
        learning_objectives=[],
        current_html="<body><p>Original</p></body>",
        instruction="Add a practice exercise",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
    )
    assert html == "<body><p>Original</p><p>Fixed</p></body>"
    assert chat_route.call_count == 2
    retry_prompt = json.loads(chat_route.calls[1].request.content)["messages"][1]["content"]
    assert "failed to apply" in retry_prompt


@respx.mock
async def test_generate_module_output_revise_falls_back_to_full_rewrite_after_two_failures():
    """If the model can't produce edits that apply even after one retry,
    the call still succeeds via a full from-scratch rewrite instead of
    failing the whole generation outright."""
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        side_effect=[
            Response(200, json={"choices": [{"message": {"content": json.dumps({"edits": [{"find": "nope", "replace": "x"}]})}}]}),
            Response(200, json={"choices": [{"message": {"content": json.dumps({"edits": [{"find": "still-nope", "replace": "x"}]})}}]}),
            Response(200, json={"choices": [{"message": {"content": "<html><body><p>Original</p><p>Rewritten</p></body></html>"}}]}),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    html = await generate_module_output(
        client,
        model="gpt-4o-mini",
        title="Module 01",
        learning_objectives=[],
        current_html="<body><p>Original</p></body>",
        instruction="Add a practice exercise",
        product_files=[],
        methodology_text="",
        feedback_notes=[],
    )
    assert html == "<html><body><p>Original</p><p>Rewritten</p></body></html>"
    assert chat_route.call_count == 3
