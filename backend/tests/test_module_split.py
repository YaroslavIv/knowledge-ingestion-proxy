import json

import respx
from httpx import Response

from app.course_generation.module_split import build_file_excerpts, build_prompt, propose_modules
from app.owui_client import OwuiClient


def test_build_file_excerpts_truncates_long_content():
    long_text = "x" * 5000
    files = [("a.txt", "short content"), ("b.txt", long_text)]
    excerpts = build_file_excerpts(files)
    assert excerpts[0] == {"filename": "a.txt", "excerpt": "short content"}
    assert excerpts[1]["filename"] == "b.txt"
    assert len(excerpts[1]["excerpt"]) == 1500


def test_build_prompt_includes_methodology_feedback_and_files():
    prompt = build_prompt(
        product_files=[{"filename": "datasheet.txt", "excerpt": "Elite supports 1000 FPS."}],
        methodology_text="Explain -> Engage -> Check -> Apply.",
        feedback_notes=["Do not re-explain product line from scratch in every module."],
        target_audience="sales",
        language="en",
    )
    assert "Explain -> Engage -> Check -> Apply." in prompt
    assert "Do not re-explain product line from scratch in every module." in prompt
    assert "datasheet.txt" in prompt
    assert "Elite supports 1000 FPS." in prompt


def test_build_prompt_handles_no_feedback_or_files():
    prompt = build_prompt([], "", [], "sales", "en")
    assert "(none yet)" in prompt
    assert "(no files)" in prompt


def test_build_prompt_lists_existing_modules_so_the_model_avoids_duplicating_them():
    prompt = build_prompt(
        [],
        "",
        [],
        "sales",
        "en",
        existing_modules=[{"title": "Module 01 — Intro", "learning_objectives": ["Explain the basics"]}],
    )
    assert "MODULES ALREADY IN THIS COURSE" in prompt
    assert "Module 01 — Intro" in prompt
    assert "Explain the basics" in prompt
    assert "do not duplicate" in prompt.lower()


def test_build_prompt_omits_existing_modules_section_when_none_given():
    prompt = build_prompt([], "", [], "sales", "en", existing_modules=[])
    assert "MODULES ALREADY IN THIS COURSE" not in prompt


@respx.mock
async def test_propose_modules_parses_llm_json_response():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "modules": [
                                        {
                                            "title": "Module 01 — Product Line",
                                            "learning_objectives": ["Explain the product tiers"],
                                            "source_refs": ["datasheet.txt"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    modules = await propose_modules(
        client,
        model="gpt-4o-mini",
        product_files=[{"filename": "datasheet.txt", "excerpt": "..."}],
        methodology_text="...",
        feedback_notes=[],
    )
    assert len(modules) == 1
    assert modules[0]["title"] == "Module 01 — Product Line"
    assert modules[0]["source_refs"] == ["datasheet.txt"]


@respx.mock
async def test_propose_modules_rejects_malformed_response():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": '{"oops": true}'}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    modules = await propose_modules(client, model="gpt-4o-mini", product_files=[], methodology_text="", feedback_notes=[])
    assert modules == []
