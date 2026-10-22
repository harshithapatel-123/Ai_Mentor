import ast
import re
from pathlib import Path

import pytest


API_FILE = Path(__file__).resolve().parents[1] / "api.py"


@pytest.fixture
def sanitize_lesson_script():
    """Load the sanitizer without importing external AI service dependencies."""
    source = API_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "sanitize_lesson_script"
    )

    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"re": re}
    exec(compile(module, str(API_FILE), "exec"), namespace)

    return namespace["sanitize_lesson_script"]


def test_removes_headings_bold_italic_and_list_markers(sanitize_lesson_script):
    text = "# Introduction\n\n**Bold text** and *italic text*\n- First item\n1. Second item"

    result = sanitize_lesson_script(text)

    assert result == "Introduction\n\nBold text and italic text\nFirst item\nSecond item"


def test_removes_inline_and_fenced_code_markers(sanitize_lesson_script):
    text = "Use `print()`.\n```python\nprint('hello')\n```"

    result = sanitize_lesson_script(text)

    assert "`" not in result
    assert "```" not in result
    assert "print()" in result
    assert "print('hello')" in result


def test_converts_markdown_links_to_readable_labels(sanitize_lesson_script):
    result = sanitize_lesson_script("Read [Python docs](https://example.com/docs).")

    assert result == "Read Python docs."


def test_preserves_paragraphs_and_normalizes_line_endings(sanitize_lesson_script):
    result = sanitize_lesson_script("First paragraph.\r\n\r\n\r\nSecond paragraph.")

    assert result == "First paragraph.\n\nSecond paragraph."


@pytest.mark.parametrize("value", [None, 123, [], {}])
def test_non_string_input_returns_empty_string(sanitize_lesson_script, value):
    assert sanitize_lesson_script(value) == ""


def test_plain_text_is_preserved(sanitize_lesson_script):
    text = "Python is useful for data analysis."

    assert sanitize_lesson_script(text) == text

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("![Python logo](https://example.com/logo.png)", "Python logo"),
        (r"Python \*is\* useful", "Python *is* useful"),
        ("**Bold and _italic_ text**", "Bold and italic text"),
        ("> Important lesson", "Important lesson"),
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("Visit <https://example.com>", "Visit https://example.com"),
        ("~~old~~ and **new**", "old and new"),
        ("### Heading\n\nText", "Heading\n\nText"),
        ("[broken link](unfinished", "[broken link](unfinished"),
    ],
)
def test_handles_additional_markdown_cases(sanitize_lesson_script, text, expected):
    assert sanitize_lesson_script(text) == expected

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\nHello", "Hello"),
        ("~~Old~~", "Old"),
        ("<div>Hello</div>", "Hello"),
        ("Visit https://example.com", "Visit https://example.com"),
        ("Hello 😊 ★", "Hello 😊 ★"),
        ("**", ""),
        ("   \n  ", ""),
        ("Text\n\n\n\nMore text", "Text\n\nMore text"),
        (r"Python \# basics", "Python # basics"),
        ("1. First\n2. Second", "First\nSecond"),
    ],
)
def test_handles_requested_markdown_edge_cases(
    sanitize_lesson_script, text, expected
):
    assert sanitize_lesson_script(text) == expected
