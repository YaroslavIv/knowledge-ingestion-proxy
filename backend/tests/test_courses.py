import json

import respx
from httpx import Response


async def _create_project(client, **overrides):
    body = {
        "name": "UVSS Onboarding",
        "product_knowledge_ids": ["kb-product"],
        "competitors_knowledge_ids": ["kb-competitors"],
        "instructions_knowledge_ids": ["kb-instructions"],
        "pedagogy_version": "v2",
        "language": "en",
        "target_audience": "sales",
    }
    body.update(overrides)
    resp = await client.post("/api/courses", json=body)
    assert resp.status_code == 200
    return resp.json()


async def test_create_and_get_course_project(client):
    project = await _create_project(client)
    assert project["name"] == "UVSS Onboarding"
    assert project["competitors_knowledge_ids"] == ["kb-competitors"]
    assert project["product_knowledge_ids"] == ["kb-product"]

    get_resp = await client.get(f"/api/courses/{project['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project["id"]


async def test_get_missing_project_404s(client):
    resp = await client.get("/api/courses/does-not-exist")
    assert resp.status_code == 404


async def test_create_project_requires_at_least_one_product_collection(client):
    resp = await client.post(
        "/api/courses",
        json={"name": "No product material", "product_knowledge_ids": [], "instructions_knowledge_ids": ["kb-i"]},
    )
    assert resp.status_code == 400


async def test_create_project_requires_at_least_one_instructions_collection(client):
    resp = await client.post(
        "/api/courses",
        json={"name": "No instructions", "product_knowledge_ids": ["kb-p"], "instructions_knowledge_ids": []},
    )
    assert resp.status_code == 400


async def test_add_and_remove_course_material(client):
    project = await _create_project(client)

    add_resp = await client.post(f"/api/courses/{project['id']}/materials", json={"knowledge_id": "kb-second"})
    assert add_resp.status_code == 200
    assert add_resp.json()["product_knowledge_ids"] == ["kb-product", "kb-second"]

    # adding the same one again is a no-op, not a duplicate
    again_resp = await client.post(f"/api/courses/{project['id']}/materials", json={"knowledge_id": "kb-second"})
    assert again_resp.json()["product_knowledge_ids"] == ["kb-product", "kb-second"]

    remove_resp = await client.delete(f"/api/courses/{project['id']}/materials/kb-product")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["product_knowledge_ids"] == ["kb-second"]


async def test_cannot_remove_the_last_product_material(client):
    project = await _create_project(client)
    resp = await client.delete(f"/api/courses/{project['id']}/materials/kb-product")
    assert resp.status_code == 400


async def test_add_and_remove_course_competitor(client):
    project = await _create_project(client)

    add_resp = await client.post(f"/api/courses/{project['id']}/competitors", json={"knowledge_id": "kb-second"})
    assert add_resp.status_code == 200
    assert add_resp.json()["competitors_knowledge_ids"] == ["kb-competitors", "kb-second"]

    remove_resp = await client.delete(f"/api/courses/{project['id']}/competitors/kb-competitors")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["competitors_knowledge_ids"] == ["kb-second"]

    # competitors is optional — removing the last one is fine
    remove_last_resp = await client.delete(f"/api/courses/{project['id']}/competitors/kb-second")
    assert remove_last_resp.status_code == 200
    assert remove_last_resp.json()["competitors_knowledge_ids"] == []


async def test_add_and_remove_course_instructions(client):
    project = await _create_project(client)

    add_resp = await client.post(f"/api/courses/{project['id']}/instructions", json={"knowledge_id": "kb-second"})
    assert add_resp.status_code == 200
    assert add_resp.json()["instructions_knowledge_ids"] == ["kb-instructions", "kb-second"]

    remove_resp = await client.delete(f"/api/courses/{project['id']}/instructions/kb-instructions")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["instructions_knowledge_ids"] == ["kb-second"]


async def test_cannot_remove_the_last_instructions_collection(client):
    project = await _create_project(client)
    resp = await client.delete(f"/api/courses/{project['id']}/instructions/kb-instructions")
    assert resp.status_code == 400


async def test_set_change_and_clear_course_visual(client):
    project = await _create_project(client)
    assert project["visual_knowledge_id"] is None

    set_resp = await client.put(f"/api/courses/{project['id']}/visual", json={"knowledge_id": "kb-visual"})
    assert set_resp.status_code == 200
    assert set_resp.json()["visual_knowledge_id"] == "kb-visual"

    changed_resp = await client.put(f"/api/courses/{project['id']}/visual", json={"knowledge_id": "kb-visual-2"})
    assert changed_resp.json()["visual_knowledge_id"] == "kb-visual-2"

    cleared_resp = await client.delete(f"/api/courses/{project['id']}/visual")
    assert cleared_resp.status_code == 200
    assert cleared_resp.json()["visual_knowledge_id"] is None


async def test_list_course_projects(client):
    await _create_project(client, name="Project A")
    await _create_project(client, name="Project B")
    resp = await client.get("/api/courses")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert {"Project A", "Project B"} <= names


async def test_seed_feedback_and_list_it(client):
    project = await _create_project(client)
    text = (
        "Общее:\n"
        "Knowledge Check – Выделить крупнее и сделать заметнее.\n\n"
        "===Module 1===\n"
        "горизонтальное перелистывание неудобно – сделай вертикальные блоки div.\n"
    )
    seed_resp = await client.post(f"/api/courses/{project['id']}/feedback/seed", json={"text": text})
    assert seed_resp.status_code == 200
    notes = seed_resp.json()
    assert len(notes) == 2
    assert any(n["category"] == "ui" for n in notes)
    # module-labelled notes get prefixed so the module hint isn't lost
    assert any(n["note_text"].startswith("[Module 1]") for n in notes)

    list_resp = await client.get(f"/api/courses/{project['id']}/feedback")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 2


async def test_manual_module_crud_and_approval_flow(client):
    project = await _create_project(client)

    create_resp = await client.post(
        f"/api/courses/{project['id']}/modules",
        json={"title": "Module 01 — Intro", "learning_objectives": ["Explain the basics"], "source_refs": ["a.txt"]},
    )
    assert create_resp.status_code == 200
    module = create_resp.json()
    assert module["status"] == "proposed"
    assert module["order_index"] == 0

    patch_resp = await client.patch(
        f"/api/courses/{project['id']}/modules/{module['id']}",
        json={"title": "Module 01 — Introduction"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Module 01 — Introduction"

    approve_resp = await client.post(f"/api/courses/{project['id']}/modules/{module['id']}/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"
    assert approve_resp.json()["approved_at"] is not None

    list_resp = await client.get(f"/api/courses/{project['id']}/modules")
    assert len(list_resp.json()) == 1

    delete_resp = await client.delete(f"/api/courses/{project['id']}/modules/{module['id']}")
    assert delete_resp.status_code == 200
    assert (await client.get(f"/api/courses/{project['id']}/modules")).json() == []


async def test_reject_module(client):
    project = await _create_project(client)
    module = (
        await client.post(f"/api/courses/{project['id']}/modules", json={"title": "Draft module"})
    ).json()
    resp = await client.post(f"/api/courses/{project['id']}/modules/{module['id']}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@respx.mock
async def test_split_into_modules_writes_proposed_rows(client):
    project = await _create_project(client)

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "Elite supports 1000 FPS."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-m", "filename": "readme.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-m/data/content").mock(
        return_value=Response(200, json={"content": "Explain -> Engage -> Check -> Apply."})
    )
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
                                            "learning_objectives": ["Explain the tiers"],
                                            "source_refs": ["datasheet.txt"],
                                        },
                                        {
                                            "title": "Module 02 — Positioning",
                                            "learning_objectives": ["Position against competitors"],
                                            "source_refs": ["datasheet.txt"],
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )
    )

    resp = await client.post(f"/api/courses/{project['id']}/split", json={"model": "gpt-4o-mini"})
    assert resp.status_code == 200
    modules = resp.json()
    assert len(modules) == 2
    assert modules[0]["title"] == "Module 01 — Product Line"
    assert modules[0]["order_index"] == 0
    assert modules[1]["order_index"] == 1
    assert all(m["status"] == "proposed" for m in modules)

    list_resp = await client.get(f"/api/courses/{project['id']}/modules")
    assert len(list_resp.json()) == 2


@respx.mock
async def test_split_is_additive_not_destructive(client):
    """Re-running the split after a human already approved a module must
    not touch that module — it only appends newly proposed ones."""
    project = await _create_project(client)
    approved = (
        await client.post(f"/api/courses/{project['id']}/modules", json={"title": "Already approved"})
    ).json()
    await client.post(f"/api/courses/{project['id']}/modules/{approved['id']}/approve")

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"modules": [{"title": "New module"}]})}}]},
        )
    )

    resp = await client.post(f"/api/courses/{project['id']}/split", json={"model": "gpt-4o-mini"})
    assert resp.status_code == 200
    assert resp.json()[0]["order_index"] == 1  # appended after the existing one

    # the model was told about the already-approved module, so it doesn't
    # blindly propose a duplicate/overlapping one
    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Already approved" in sent_prompt

    all_modules = (await client.get(f"/api/courses/{project['id']}/modules")).json()
    assert len(all_modules) == 2
    still_approved = next(m for m in all_modules if m["id"] == approved["id"])
    assert still_approved["status"] == "approved"


async def test_delete_project_cascades_modules_and_feedback(client):
    project = await _create_project(client)
    await client.post(f"/api/courses/{project['id']}/modules", json={"title": "M1"})
    await client.post(f"/api/courses/{project['id']}/feedback/seed", json={"text": "A general note.\n"})

    delete_resp = await client.delete(f"/api/courses/{project['id']}")
    assert delete_resp.status_code == 200

    assert (await client.get(f"/api/courses/{project['id']}")).status_code == 404


@respx.mock
async def test_delete_module_cleans_up_its_published_output_in_open_webui(client):
    """A module with a published output has real files sitting in Open
    WebUI (a manifest linked into the output KB, plus a raw artifact that's
    never linked into any KB) — deleting the module locally must also clean
    those up, not just drop the local row and leave orphans behind."""
    project = await _create_project(client)
    module = (await client.post(f"/api/courses/{project['id']}/modules", json={"title": "M1"})).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-1", "filename": "m1.zip"}),
            Response(200, json={"id": "manifest-1", "filename": "m.md"}),
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("m1.zip", b"PK\x03\x04somebytes", "application/zip")},
    )

    unlink_route = respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/remove").mock(
        return_value=Response(200)
    )
    delete_raw_route = respx.delete("http://fake-owui.test/api/v1/files/raw-1").mock(return_value=Response(200))

    resp = await client.delete(f"/api/courses/{project['id']}/modules/{module['id']}")
    assert resp.status_code == 200

    assert unlink_route.called
    assert json.loads(unlink_route.calls[0].request.content) == {"file_id": "manifest-1"}
    assert delete_raw_route.called

    assert (await client.get(f"/api/courses/{project['id']}/modules")).json() == []


@respx.mock
async def test_delete_project_cleans_up_the_whole_output_kb_and_raw_files(client):
    """Deleting a project must not leave its entire output knowledge base
    (and every raw published artifact, which lives outside any KB) behind
    in Open WebUI forever."""
    project = await _create_project(client)
    module = (await client.post(f"/api/courses/{project['id']}/modules", json={"title": "M1"})).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-1", "filename": "m1.zip"}),
            Response(200, json={"id": "manifest-1", "filename": "m.md"}),
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("m1.zip", b"PK\x03\x04somebytes", "application/zip")},
    )

    delete_kb_route = respx.delete("http://fake-owui.test/api/v1/knowledge/kb-output/delete").mock(
        return_value=Response(200, json=True)
    )
    delete_raw_route = respx.delete("http://fake-owui.test/api/v1/files/raw-1").mock(return_value=Response(200))

    resp = await client.delete(f"/api/courses/{project['id']}")
    assert resp.status_code == 200

    assert delete_kb_route.called
    assert delete_raw_route.called


@respx.mock
async def test_list_available_models(client):
    respx.get("http://fake-owui.test/api/v1/models").mock(
        return_value=Response(200, json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o", "name": "GPT-4o"}]})
    )
    resp = await client.get("/api/courses/available-models")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["id"] == "gpt-4o-mini"
    assert body[1]["name"] == "GPT-4o"
