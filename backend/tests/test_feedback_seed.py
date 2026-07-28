from app.course_generation.feedback_seed import parse_feedback_file

SAMPLE = """\
Общее:
Knowledge Check – Выделить крупнее и сделать заметнее.

По курсу Product line несколько раз повторяется почти с нуля.

===Module 1===
Part 2: горизонтальное перелистывание тем неудобно – сделай вертикальные блоки div.

=== Module 4===
Неверная информация:
«What mobile UVSS is»
Corrected text here.

=== PRACTICAL CASES===
Добавь пожалуйста кнопку «Завершить курс».
"""


def test_parses_general_notes_before_first_module_marker():
    notes = parse_feedback_file(SAMPLE)
    general = [n for n in notes if n.module_label is None]
    assert len(general) == 2
    assert general[0].category == "ui"
    assert general[1].category == "content_repetition"


def test_parses_module_sections_regardless_of_marker_spacing():
    notes = parse_feedback_file(SAMPLE)
    labels = {n.module_label for n in notes if n.module_label}
    assert labels == {"Module 1", "Module 4", "PRACTICAL CASES"}


def test_categorizes_ui_and_factual_and_packaging_notes():
    notes = parse_feedback_file(SAMPLE)
    by_label = {n.module_label: n for n in notes if n.module_label}
    assert by_label["Module 1"].category == "ui"
    assert by_label["Module 4"].category == "factual_error"
    assert by_label["PRACTICAL CASES"].category == "packaging"


def test_sequencing_complaint_is_structure_not_ui_despite_shared_vocabulary():
    text = "===Module 6===\nНекорректная последовательность подзаголовков в модуле.\n"
    notes = parse_feedback_file(text)
    assert len(notes) == 1
    assert notes[0].category == "structure"


def test_empty_text_yields_no_notes():
    assert parse_feedback_file("") == []


def test_blank_lines_do_not_produce_empty_notes():
    text = "===Module 1===\n\n\nOne real note.\n\n\n"
    notes = parse_feedback_file(text)
    assert len(notes) == 1
    assert notes[0].note_text == "One real note."
