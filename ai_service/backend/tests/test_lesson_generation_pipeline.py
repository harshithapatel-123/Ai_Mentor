import ast
import asyncio
import os
import re
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest


API_FILE = Path(__file__).resolve().parents[1] / "api.py"


def load_pipeline(tmp_path, monkeypatch, gemini_text=None,
                  gemini_error=None, groq_text=None, groq_error=None):
    source = API_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"sanitize_lesson_script", "process_lesson"}
    ]
    assert len(functions) == 2

    class LessonRequest:
        pass

    video_input = tmp_path / "input.mp4"
    video_input.write_bytes(b"video")

    def fake_system(command):
        output_path = Path(command.split('"')[-2])
        output_path.write_bytes(b"generated video")
        return 0

    fake_os = SimpleNamespace(
        path=os.path,
        makedirs=os.makedirs,
        remove=os.remove,
        exists=os.path.exists,
        system=fake_system,
    )

    class FakeGemini:
        class Models:
            def generate_content(self, **kwargs):
                if gemini_error:
                    raise gemini_error
                return SimpleNamespace(text=gemini_text)

        models = Models()

    class FakeGroq:
        class Chat:
            class Completions:
                def create(self, **kwargs):
                    if groq_error:
                        raise groq_error
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content=groq_text)
                            )
                        ]
                    )

            completions = Completions()

        chat = Chat()

    spoken_text = []

    async def fake_tts(text, output_file):
        spoken_text.append(text)
        Path(output_file).write_bytes(b"audio")

    namespace = {
        "os": fake_os,
        "re": re,
        "asyncio": asyncio,
        "traceback": traceback,
        "LessonRequest": LessonRequest,
        "BASE_DIR": str(tmp_path),
        "gemini_client": FakeGemini(),
        "groq_client": FakeGroq(),
        "generate_tts": fake_tts,
        "get_celebrity_video": lambda celebrity: str(video_input),
        "cloudinary": SimpleNamespace(
            uploader=SimpleNamespace(
                upload=lambda *args, **kwargs: {"secure_url": None}
            )
        ),
        "job_status": {},
    }

    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(module, str(API_FILE), "exec"), namespace)

    return namespace, spoken_text


def make_request(namespace):
    return SimpleNamespace(
        course="Python",
        topic="Variables",
        celebrity="modi",
        preferences=None,
        dict=lambda: {
            "course": "Python",
            "topic": "Variables",
            "celebrity": "modi",
        },
    )


def test_gemini_script_is_sanitized_saved_and_sent_to_tts(tmp_path, monkeypatch):
    namespace, spoken = load_pipeline(
        tmp_path,
        monkeypatch,
        gemini_text="## **Python** is useful.",
    )

    namespace["process_lesson"](make_request(namespace), "gemini_test")

    transcript = tmp_path / "outputs" / "text" / "gemini_test.txt"
    assert transcript.read_text(encoding="utf-8") == "Python is useful."
    assert spoken == ["Python is useful."]
    assert namespace["job_status"]["gemini_test"]["status"] == "ready"


def test_groq_fallback_script_is_sanitized_and_saved(tmp_path, monkeypatch):
    namespace, spoken = load_pipeline(
        tmp_path,
        monkeypatch,
        gemini_error=RuntimeError("Gemini unavailable"),
        groq_text="**Fallback** lesson.",
    )

    namespace["process_lesson"](make_request(namespace), "groq_test")

    transcript = tmp_path / "outputs" / "text" / "groq_test.txt"
    assert transcript.read_text(encoding="utf-8") == "Fallback lesson."
    assert spoken == ["Fallback lesson."]
    assert namespace["job_status"]["groq_test"]["status"] == "ready"


def test_both_ai_providers_failing_marks_job_failed(tmp_path, monkeypatch):
    namespace, spoken = load_pipeline(
        tmp_path,
        monkeypatch,
        gemini_error=RuntimeError("Gemini unavailable"),
        groq_error=RuntimeError("Groq unavailable"),
    )

    namespace["process_lesson"](make_request(namespace), "failed_test")

    assert namespace["job_status"]["failed_test"]["status"] == "failed"
    assert spoken == []
    assert not (tmp_path / "outputs" / "text" / "failed_test.txt").exists()


def test_empty_generated_script_does_not_reach_tts(tmp_path, monkeypatch):
    namespace, spoken = load_pipeline(
        tmp_path,
        monkeypatch,
        gemini_text="**",
    )

    namespace["process_lesson"](make_request(namespace), "empty_test")

    assert namespace["job_status"]["empty_test"]["status"] == "failed"
    assert spoken == []