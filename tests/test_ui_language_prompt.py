"""Unit test: UI-language output instruction on the AI prompt builders.

Run: python3 tests/test_ui_language_prompt.py  (from the project root)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import assess  # noqa: E402

RUBRIC = {"id": "att-exp-ecrite", "name": "Grille LVB Expression écrite",
          "criteria": [{"name": "Simplicité et clarté", "description": "…"}],
          "attestation": True}
STATS = {"evaluations": 2, "by_class": [], "evaluations_detail": [
    {"student": "Alice", "classroom": "26/27-X-1", "criteria": {},
     "overall": "B1", "feedback": {"key_success": "…", "target_area": "…",
                                   "comment": "…"}}]}
ASSIGNMENT = {"name": "Sujet test", "target_level": "B1",
              "skill": "expression", "kind": "written",
              "instruction": "Write a review", "document_text": "",
              "eval_notes": ""}


def _user_text(messages):
    m = messages[1]
    c = m["content"]
    if isinstance(c, str):
        return c
    return "".join(p.get("text", "") for p in c if p.get("type") == "text")


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


def main():
    # language_instruction()
    check(assess._ui_language("FR ") == "fr", "ui_language normalises FR→fr")
    check(assess._ui_language(None) == "", "None → ''")
    check("OUTPUT LANGUAGE" in assess.language_instruction("fr"),
          "fr block present")
    check("French" in assess.language_instruction("fr"), "names French")
    check("MANDATORY" in assess.language_instruction("fr"), "fr block marked mandatory")
    check(assess.language_instruction("") == "", "empty → no block")
    check(assess.language_instruction("xx") == "", "unknown code → no block")
    # language_system_line()
    check("OUTPUT LANGUAGE" in assess.language_system_line("fr"),
          "fr system line present")
    check(assess.language_system_line("") == "", "system line empty when no lang")
    check(assess.language_system_line("xx") == "", "system line empty when unknown")

    # build_messages: FR present, EN absent, no-legacy unchanged
    fr = assess.build_messages(kind="written", rubric=RUBRIC,
                               student_context="", written_text="It was a cat.",
                               ui_language="fr")
    txt_fr = _user_text(fr)
    check("OUTPUT LANGUAGE — MANDATORY: the teacher's interface is in French"
          in txt_fr,
          "build_messages(fr) carries the French block")
    check("OUTPUT LANGUAGE (mandatory)" in fr[0]["content"],
          "system prompt carries the mandatory FR line")
    check("It was a cat." in txt_fr, "verbatim copy preserved in prompt")

    en = assess.build_messages(kind="written", rubric=RUBRIC,
                               student_context="", written_text="It was a cat.",
                               ui_language="en")
    check("OUTPUT LANGUAGE — MANDATORY: the teacher's interface is in English"
          in _user_text(en),
          "build_messages(en): explicit English block")

    legacy = assess.build_messages(kind="written", rubric=RUBRIC,
                                   student_context="",
                                   written_text="It was a cat.")
    check("OUTPUT LANGUAGE" not in _user_text(legacy)
          and "OUTPUT LANGUAGE" not in legacy[0]["content"],
          "no ui_language → legacy prompt unchanged (user + system)")

    # aware-mode path also honours it (teacher_levels + ui_language)
    aware = assess.build_messages(kind="written", rubric=RUBRIC,
                                  student_context="",
                                  written_text="It was a cat.",
                                  teacher_levels={"Simplicité et clarté": "B2"},
                                  ui_language="de")
    check("OUTPUT LANGUAGE" in _user_text(aware) and "German" in _user_text(aware),
          "aware mode + de → German block")

    # class insight
    ci_fr = assess.build_class_insight_messages(
        assignment=ASSIGNMENT, stats=STATS, ui_language="fr")
    check("OUTPUT LANGUAGE" in _user_text(ci_fr), "class insight (fr) block")
    ci_none = assess.build_class_insight_messages(
        assignment=ASSIGNMENT, stats=STATS)
    check("OUTPUT LANGUAGE" not in _user_text(ci_none),
          "class insight legacy unchanged")

    print("\nAll UI-language prompt checks passed ✓")


if __name__ == "__main__":
    main()
