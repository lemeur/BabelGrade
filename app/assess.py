"""Assessment pipeline: prompt building, fluency metrics, JSON parsing.

The core promise: map linguistic evidence to CEFR rubric descriptors with
verbatim quotes / timestamps. No level is asserted without a concrete quote.
"""
import json
from typing import Optional

# ---------------------------------------------------------------- system prompt
SYSTEM_PROMPT = """You are an expert ELT (English Language Teaching) assessment
assistant for a teacher. You act as an OBJECTIVE EVIDENCE EXTRACTOR, not a
grade-substituter: you map linguistic evidence directly to CEFR rubric
descriptors to lower the teacher's cognitive load. The teacher makes the final
call.

Operating rules:
- Written input: read/OCR the student copy faithfully. The copy may span
  several page photos in reading order: treat them as ONE continuous text.
  Identify B2/C1 lexicon,
  complex structures (passives, modal perfects, inversion, conditionals,
  clefts, inversion), logical connectors and discourse markers. Note recurring
  (not isolated) morphological / syntactic / spelling errors.
- Oral input: you are given a transcript WITH timestamps plus computed fluency
  metadata (WPM, pauses, hesitations). You CANNOT hear the audio; base
  phonological claims only on what the transcript text implies, and always cite
  a timestamp so the teacher can verify in the recording.
- Every suggested CEFR level must be justified with a verbatim quote, line or
  timestamp from the student's own work. Never assert a level without concrete
  evidence.
- Maintain neutrality and consistency; avoid halo effects and evaluator fatigue.
- Present everything as a recommendation the teacher can validate or override.
- When a TARGET LEVEL is provided, still assess the demonstrated level objectively
  from the evidence first; the target only frames the final comparison
  (meets / below / above). Never inflate or deflate the level to match the target.

Tone: professional, objective, pedagogically encouraging.
"""


def _fmt_ts(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}"


# ---------------------------------------------------------------- fluency metrics
_FILLERS = {
    "um", "uh", "er", "erm", "oh", "mmm", "mm", "hmm", "like", "so",
    "you know", "i mean", "right", "kind of", "sort of",
}


def fluency_metrics(transcript: dict) -> dict:
    """Compute real fluency parameters from Whisper word/segment timings."""
    words = transcript.get("words", [])
    segs = transcript.get("segments", [])
    text_words = [w for w in words if w["w"]]
    wpm = transcript.get("wpm", 0)
    dur = transcript.get("duration_s", 0)

    # pause gaps between consecutive words
    pauses = []
    for a, b in zip(text_words, text_words[1:]):
        gap = b["start"] - a["end"]
        if gap >= 0.6:
            pauses.append({"after": a["w"], "at_s": round(a["end"], 1),
                           "gap_s": round(gap, 2)})
    notable = [p for p in pauses if p["gap_s"] >= 1.2]

    # filler / hesitation tokens
    fillers = []
    for w in text_words:
        lw = w["w"].lower().strip(",.;!?()")
        if lw in _FILLERS or w["prob"] < 0.45:
            fillers.append({"w": w["w"], "at_s": w["start"]})
    hesitation_count = len(fillers)

    return {
        "duration_s": dur,
        "wpm": wpm,
        "word_count": len(text_words),
        "segment_count": len(segs),
        "pause_count_total": len(pauses),
        "notable_pause_count": len(notable),
        "longest_pause_s": round(max([p["gap_s"] for p in pauses], default=0), 2),
        "hesitation_count": hesitation_count,
        "hesitation_examples": [f"[{_fmt_ts(f['at_s'])}] {f['w']}" for f in fillers[:12]],
        "note": ("Fluency metrics computed from local Whisper (faster-whisper) "
                 "timings. Phonological claims are transcript-based: the model "
                 "analyzes text, not the audio waveform."),
    }


# ---------------------------------------------------------------- transcript with timestamps
def transcript_with_timestamps(transcript: dict) -> str:
    """Render segments as timestamped lines the LLM can cite."""
    lines = []
    for s in transcript.get("segments", []):
        lines.append(f"[{_fmt_ts(s['start'])} -> {_fmt_ts(s['end'])}] {s['text'].strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------- prompt builders
DOC_CHAR_CAP = 12000


def _assignment_context_block(context: dict) -> str:
    """Render the assignment context (instruction + source document) for the prompt."""
    parts = []
    instr = (context.get("instruction") or "").strip()
    doc = (context.get("document_text") or "").strip()
    doc_images = list(context.get("document_images") or [])
    instr_photos = list(context.get("instruction_photo_urls") or [])
    doc_photos = list(context.get("document_photo_urls") or [])
    if instr:
        parts.append(f"ASSIGNMENT INSTRUCTION (the work given to the student):\n{instr}")
    if instr_photos and not instr:
        parts.append(
            f"ASSIGNMENT INSTRUCTION: the assignment was provided as {len(instr_photos)} "
            f"photo(s) (attached to this message after the student's copy photos) — "
            f"read them to know what the student had to produce."
        )
    if doc:
        src = context.get("document_source")
        note = ""
        if src == "audio":
            note = " (transcribed from the audio provided with the assignment)"
        if src == "pdf":
            note = " (extracted from the PDF provided with the assignment)"
        if len(doc) > DOC_CHAR_CAP:
            doc = doc[:DOC_CHAR_CAP] + "\n[...document truncated...]"
        parts.append(f"SOURCE DOCUMENT{note} (the text/audio the student's work is based on):\n{doc}")
    if doc_images and not doc:
        parts.append(
            f"SOURCE DOCUMENT: the source document was provided as a {len(doc_images)}-page "
            f"scanned PDF (no text layer). The page image(s) are attached to this message — "
            f"read them as the document the student's work is based on."
        )
    if doc_photos and not doc:
        parts.append(
            f"SOURCE DOCUMENT: the source document was provided as {len(doc_photos)} "
            f"photo(s) of a printed document (attached to this message — the last "
            f"{len(doc_photos)} image(s)). Read them as the document the student's "
            f"work is based on."
        )
    parts.append(
        "Use this context to judge the work against THE ASSIGNMENT: the instruction defines "
        "what the student had to produce (assignment type, length, focus, questions to answer, "
        "document to react to). A strong performance fulfills the assignment, not just generic "
        "quality. In the content criterion justification and the student feedback, refer "
        "to the assignment requirements explicitly; you may quote short snippets of the assignment "
        "instruction/document in evidence to show what was or was not addressed."
    )
    return "ASSIGNMENT CONTEXT:\n" + "\n\n".join(parts)


def _eval_notes_block(eval_notes: dict) -> str:
    """Render the teacher's evaluation instructions (what to check) for the prompt."""
    notes = (eval_notes.get("text") or "").strip()
    pages = list(eval_notes.get("pdf_pages") or [])
    photos = list(eval_notes.get("photo_urls") or [])
    cap = DOC_CHAR_CAP
    if len(notes) > cap:
        notes = notes[:cap] + "\n[…notes truncated…]"
    lines = []
    if notes:
        lines.append(notes)
    if pages:
        lines.append(
            f"(the evaluation instructions were also provided as a {len(pages)}-page "
            f"scanned PDF with no text layer — its page image(s) are attached to this "
            f"message as the LAST {len(pages)} image(s); read them in full.)"
        )
    if photos:
        lines.append(
            f"(the evaluation instructions were also provided as {len(photos)} "
            f"photo(s) of a printed sheet — the page image(s) are attached to this "
            f"message as the LAST {len(photos)} image(s); read them in full.)"
        )
    lines.append(
        "Check EVERY point the teacher asks for above, one by one, against the "
        "student's actual work. For each point state in the relevant criterion "
        "justification and in 'student_feedback' whether it is met, partially met "
        "or missing, and cite the verbatim evidence (or its absence) that shows "
        "it. These instructions are evaluation requirements: they can only "
        "affect the content/assignment assessment and the feedback, never the "
        "demonstrated language level."
    )
    return "EVALUATION INSTRUCTIONS (set by the teacher — what to check in this work):\n" \
        + "\n".join(lines)


def _accommodations_block(text: str) -> str:
    """Render per-student evaluation accommodations for the prompt."""
    return (
        "STUDENT EVALUATION ACCOMMODATIONS (set by the teacher for this "
        "candidate — apply them when grading this specific work):\n"
        f"{text}\n"
        "These accommodations change how strictly certain aspects are "
        "counted (e.g. spelling mistakes weighed less for a dyslexic "
        "student, extra time reflected in length expectations). State in "
        "'student_feedback' which accommodations were applied. They never "
        "change the demonstrated language level itself."
    )


def _pre_annotations_block(annotations: list, kind: str) -> str:
    """Render the teacher's pre-annotations (highlighted passages with emoji
    stickers + estimated per-passage level) for the prompt.

    These are the teacher's eyes already on specific passages: a 👍 marks a
    passage the teacher considers a strength, 👎/😠 a weak one, and each may
    carry an estimated CEFR level that applies ONLY to that passage. The AI
    must use them as anchors: when justifying a criterion it should refer to
    the annotated passages (by number and verbatim text / [mm:ss]), and the
    per-passage levels are strong signals for the demonstrated level.
    """
    if not annotations:
        return ""
    lines = []
    for a in annotations:
        sp = a.get("span") or {}
        lvl = (a.get("level") or "").strip().upper()
        sticker = a.get("sticker") or "📌"
        note = (a.get("note") or "").strip()
        if kind == "oral":
            s, e = sp.get("start_s"), sp.get("end_s")
            loc = f"[{_fmt_ts(s or 0)} → {_fmt_ts(e or 0)}]"
        else:
            page = a.get("page")
            loc = f"(page {page + 1})" if page is not None else ""
        entry = (f"- ANNOTATION {a.get('id')} {sticker} {loc} "
                 f"estimated passage level: {lvl or 'n/a'}"
                 + (f" — teacher note: {note}" if note else ""))
        q = (a.get("quote") or "").strip()
        if q:
            entry += f"\n  Passage: {q}"
        lines.append(entry)
    return (
        "TEACHER'S PRE-ANNOTATIONS (passages the teacher highlighted on the "
        "student's work BEFORE this AI evaluation, each with an emoji marker "
        "and an estimated CEFR level for THAT passage only):\n"
        + "\n".join(lines)
        + "\nUse these as ANCHORS, not as the full picture: (1) when "
        "justifying a criterion, explicitly refer to the relevant annotated "
        "passage(s) by number and quote them verbatim (with [mm:ss] for oral); "
        "(2) the per-passage levels are a strong signal — weigh them when "
        "deciding the overall demonstrated level, but still judge the whole "
        "work; a single 👍 passage does not define the candidate; (3) passages "
        "marked 👍 are strengths to cite in 'strong_points' unless your "
        "reading of the evidence shows otherwise."
    )


# ---------------------------------------------------------------- output language
UI_LANG_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German",
}


def _ui_language(name: str) -> str:
    """Normalise a UI language code; '' when unknown/absent."""
    return (name or "").strip().lower() or ""


def language_instruction(ui_language: str) -> str:
    """Prompt block asking the model to write its prose fields in the UI's
    language. Returns '' when the language is unknown (legacy behavior:
    the model picks freely — usually English)."""
    lang = _ui_language(ui_language)
    name = UI_LANG_NAMES.get(lang)
    if not name:
        return ""
    return (
        f"OUTPUT LANGUAGE — MANDATORY: the teacher's interface is in {name}, so "
        f"your WHOLE reply must be written in {name}. Every prose field is in "
        f"{name}: 'executive_summary', every 'justification' and 'note', every "
        "entry of 'strong_points' / 'areas_for_improvement', and all of "
        "'student_feedback'. Do NOT default to English just because the "
        "student's work is in English. VERBATIM quotes from the student's "
        "work MUST stay in the student's original language — only the text "
        f"around them is in {name}. Level codes (A1–C2), [mm:ss] timestamps "
        "and the 'confidence' / 'versus_target' values never change."
    )


def language_system_line(ui_language: str) -> str:
    """Short mandatory-language line appended to the SYSTEM prompt (models
    weigh system instructions most — a 2026-10-16 run showed the user-side
    block alone was sometimes ignored). '' when unknown."""
    lang = _ui_language(ui_language)
    name = UI_LANG_NAMES.get(lang)
    if not name:
        return ""
    return (f"OUTPUT LANGUAGE (mandatory): write every prose field of your JSON "
            f"reply in {name}; verbatim quotes from the student's work keep "
            f"their original language.")


def _teacher_levels_block(levels: dict) -> str:
    """Render the teacher's per-criterion levels for the "aware" AI mode.

    In this mode the AI does NOT grade from scratch: it reviews the
    teacher's levels and must CONFIRM or REFUTE each one, with verbatim
    evidence. (Blind mode omits this block entirely.)
    """
    lines = []
    for name, lvl in (levels or {}).items():
        lvl = (lvl or "").strip().upper()
        lines.append(f"- {name}: {lvl if lvl else '(not yet rated)'}")
    return (
        "TEACHER'S LEVELS (the teacher has already rated each criterion; you are in "
        "REVIEW mode, not a fresh grading pass):\n"
        + "\n".join(lines)
        + "\nFor EACH criterion above, decide whether the teacher's level is right: "
        "CONFIRM it or REFUTE it, always with verbatim evidence from the student's "
        "work. Your 'suggested_level' is YOUR independent judgment of the demonstrated "
        "level. When it matches the teacher's level, say so in the justification "
        "(e.g. 'Je confirme le B1 : …'); when it differs, state the target level and "
        "explain the gap with evidence. In 'student_feedback', frame the comment as a "
        "review of the teacher's evaluation — what you confirm and what you would raise "
        "or lower — rather than a first-pass summary."
    )


def build_messages(*, kind: str, rubric: dict, student_context: str,
                   written_text: Optional[str] = None,
                   image_data_url: Optional[str] = None,
                   image_data_urls: Optional[list] = None,
                   oral_transcript: Optional[str] = None,
                   oral_metadata: Optional[dict] = None,
                   target_level: Optional[str] = None,
                   assignment_context: Optional[dict] = None,
                   eval_notes: Optional[dict] = None,
                   accommodations: Optional[str] = None,
                   teacher_levels: Optional[dict] = None,
                   pre_annotations: Optional[list] = None,
                   transcript_corrected: bool = False,
                   ui_language: Optional[str] = None) -> list[dict]:
    images = list(image_data_urls or [])
    if not images and image_data_url:
        images = [image_data_url]
    criteria_block = "\n".join(
        f"- {c['name']}: {c['description']}" for c in rubric["criteria"]
    )

    schema = """{
  "executive_summary": "string: 2-3 sentence overall performance level",
  "overall_level": "string e.g. 'B1+' | 'B2' | 'C1-'",
  "versus_target": "meets|below|above|n/a (comparison of demonstrated level to the target level; 'n/a' if no target was given)",
  "confidence": "high|medium|low",
  "strong_points": [ {"quote": "verbatim quote/line/timestamp", "type": "lexis|syntax|cohesion|task|fluency", "level": "CEFR", "note": "short note"} ],
  "areas_for_improvement": [ {"pattern": "recurring error/pattern", "domain": "morphosyntax|lexis|cohesion|task|fluency|phonology", "evidence": ["verbatim quote or [mm:ss]"] } ],
  "rubric_mapping": [ {"criterion": "criterion name exactly as given", "suggested_level": "CEFR level", "justification": "why this level", "evidence": ["verbatim quote / line / [mm:ss]", "..."] } ],
  "student_feedback": { "key_success": "one concrete success", "target_area": "one area to work on", "comment": "short constructive, encouraging comment ready to send to the student" }
}"""

    user_parts = [f"RUBRIC: {rubric['name']} (mode: {kind})\nCriteria:\n{criteria_block}"]
    if rubric.get("attestation"):
        user_parts.append(
            "ATTESTATION LVA/LVB (grille officielle):\n"
            "Chaque critère possède sa grille A1->C2 dans sa description. Pour CHAQUE "
            "critère, 'suggested_level' DOIT être exactement l'un des niveaux : A1, A2, B1, B2, C1, C2 "
            "(pas de modificatifs '+/-', pas de niveaux combinés). Choisis le niveau CEFR dont le "
            "descripteur correspond le mieux à la performance démontrée du candidat pour ce "
            "critère, et cite les preuves. C'est une recommandation pour l'enseignant ; le "
            "score d'attestation (A1=1, A2=3, B1=5, B2=10, C1=20, C2=30 points, total /120) "
            "sera calculé à partir de ces niveaux."
        )
    if student_context:
        user_parts.append(f"STUDENT / CONTEXT:\n{student_context}")
    if target_level:
        user_parts.append(
            f"TARGET LEVEL (expected level for this candidate, set by the teacher): {target_level}.\n"
            "Evaluate the demonstrated level against this target: 'versus_target' must be "
            "'meets' (at the target), 'below' or 'above'. Mention the gap to the target "
            "(and whether it is close or significant) in the executive summary."
        )

    tc = assignment_context or {}
    if (tc.get("instruction") or "").strip() or (tc.get("document_text") or "").strip() \
            or tc.get("document_images") or tc.get("instruction_photo_urls") \
            or tc.get("document_photo_urls"):
        user_parts.append(_assignment_context_block(tc))

    en = eval_notes or {}
    if ((en.get("text") or "").strip() or en.get("pdf_pages")
            or en.get("photo_urls")):
        user_parts.append(_eval_notes_block(en))

    if (accommodations or "").strip():
        user_parts.append(_accommodations_block(accommodations.strip()))

    if teacher_levels:
        user_parts.append(_teacher_levels_block(teacher_levels))

    pa = pre_annotations or []
    if pa:
        user_parts.append(_pre_annotations_block(pa, kind))

    if kind == "written":
        wtext = (written_text or "").strip()
        if images:
            page_note = (f"The student's written copy is provided as {len(images)} photo(s), "
                         f"in reading order (page 1 to page {len(images)}). "
                         "OCR ALL pages faithfully and analyze them TOGETHER as one "
                         "continuous text: do not stop at the first page, and take the "
                         "whole submission into account when judging content, "
                         "coherence and control. When citing evidence, you may refer to "
                         "the page (e.g. 'page 2') to help the teacher locate it. "
                         "If additional images follow these in this message, they are "
                         "ASSIGNMENT MATERIALS (source document), not part of the "
                         "student's work — do not grade them.")
            user_parts.append(
                "STUDENT WRITTEN WORK:\n"
                + (wtext + "\n\n" if wtext else "")
                + page_note
                + ("\n\nA pasted transcription was also provided: treat the photos as the ground truth for the actual wording and use the text as a reference only."
                   if wtext else "")
            )
        else:
            user_parts.append(
                "STUDENT WRITTEN WORK:\n"
                + wtext
                + "\n\nAnalyze the student's written work above."
            )
    else:
        corr_note = (
            "NOTE: this transcript has been CORRECTED by the teacher "
            "(the ASR engine misheard some words). The timestamps still "
            "come from the original ASR pass, but treat the TEXT below as "
            "the ground truth — the teacher's corrected wording is what "
            "the candidate actually said."
            if transcript_corrected else
            "NOTE: this transcript comes from local ASR (Whisper); some "
            "words may be misheard."
        )
        user_parts.append(
            "STUDENT ORAL TRANSCRIPT (with timestamps):\n"
            f"{oral_transcript}\n\n"
            f"{corr_note}\n\n"
            "COMPUTED FLUENCY METADATA (from local ASR timing):\n"
            f"{json.dumps(oral_metadata or {}, indent=2)}\n"
        )

    lang_block = language_instruction(ui_language or "")
    lang_sys = language_system_line(ui_language or "")
    if lang_block:
        user_parts.append(lang_block)

    user_parts.append(
        "\nProduce the Objective Evidence Mapping following the exact JSON schema "
        "below. For 'rubric_mapping', include ONE entry for EACH criterion listed "
        "above, in the same order, using the exact criterion names.\n"
        "Respond with ONLY a valid JSON object. No markdown fences, no prose before/after."
        "\nJSON SCHEMA:\n" + schema
    )

    user_text = "\n\n".join(user_parts)

    # Assemble user content: student-copy page photos, then assignment-context images
    # (instruction photos, then source-document photos / scanned-PDF pages),
    # then scanned evaluation-instruction pages — all as multipart image parts
    # in a single user message.
    tc2 = assignment_context or {}
    en2 = eval_notes or {}
    all_images = (list(images)
                  + list(tc2.get("instruction_photo_urls") or [])
                  + list(tc2.get("document_photo_urls") or [])
                  + list(tc2.get("document_images") or [])
                  + list(en2.get("pdf_pages") or [])
                  + list(en2.get("photo_urls") or []))
    if all_images:
        content = [{"type": "text", "text": user_text}]
        content += [{"type": "image_url", "image_url": {"url": url}}
                    for url in all_images]
    else:
        content = user_text

    return [
        {"role": "system",
         "content": SYSTEM_PROMPT + ("\n\n" + lang_sys if lang_sys else "")},
        {"role": "user", "content": content},
    ]


# ------------------------------------------------- class insight prompt (stats AI)
CLASS_INSIGHT_SYSTEM_PROMPT = """You are an expert ELT (English Language Teaching)
assessment assistant for a teacher. Your task: analyze how a WHOLE CLASS
performed on one assignment, from its evaluations.

You are given:
- THE ASSIGNMENT: instruction, source document, expected target level — read
  them carefully; the "repères" (what the teacher wants checked) are defined by
  these materials and any evaluation instructions.
- THE EVALUATIONS: one line per evaluated student (level per criterion + overall
  level) followed by each student's AI evaluation summary (key success, target
  area, short comment).
- THE STATISTICS: per-class distributions (gaussians) and mean/median/σ on the
  0–30 point scale.

Analyze:
1. THE CLASS'S LEVEL: where does the class sit relative to the target level?
   Which CEFR level is dominant / typical?
2. HETEROGENEITY: is the spread narrow or wide? Who is clearly above / below?
   Which classes differ from each other (when several classes are present)?
3. WHAT WORKED WELL: the recurring strengths the students show (task fulfilment,
   lexis, syntax, task completion…) — grounded in the summaries.
4. WHAT CAUSED PROBLEMS: the recurring difficulties / weak criteria / error
   patterns — and, when it looks assignment-related (difficult question,
   ambiguous instruction, document gap), say so explicitly.

Operating rules:
- Ground every claim in the data you were given; when you name a pattern, cite
  the students / classes that show it (by name, as provided).
- Never invent student names, quotes or evaluations that are not in the input.
- Be concrete and actionable for the teacher: what to re-teach, who to pull up,
  who to stretch.
- Keep each bullet short (one line when possible); the teacher reads this on a
  phone.

Tone: professional, objective, pedagogically encouraging.
"""

CLASS_INSIGHT_SCHEMA = """{
  "class_level": "string: 2-3 sentence positioning of the class level vs the target",
  "class_level_pill": "one of: A1, A2, B1, B2, C1, C2, mixed",
  "heterogeneity": "string: short assessment of the spread (narrow/moderate/wide) and who stands out above or below",
  "what_worked": [ "strings: 2-4 bullets, each naming the strength + which students/classes show it" ],
  "what_caused_problems": [ "strings: 2-4 bullets, each naming the difficulty/error pattern + which students/classes; flag assignment-related causes (hard question, instruction, document) when present" ],
  "recommendations": [ "strings: 2-4 concrete next steps for the teacher (re-teach, group, stretch, …)" ],
  "notes": "string: caveats (small sample, mixed rubrics, missing levels, …) or empty"
}"""


def _moment_line(d: dict) -> str:
    """Compact 'μ x · M y · σ z (n=N)' line for a moments dict; '—' if empty."""
    if not isinstance(d, dict) or "mean" not in d:
        return "—"
    return (f"μ {d.get('mean')} · M {d.get('median')} · σ {d.get('sigma')}"
            f" (n={d.get('n')})")


def class_insight_language_instruction(ui_language: str) -> str:
    """Variant of language_instruction() for the class-insight JSON schema."""
    lang = _ui_language(ui_language)
    name = UI_LANG_NAMES.get(lang)
    if not name:
        return ""
    return (
        f"OUTPUT LANGUAGE — MANDATORY: the teacher's interface is in {name}, so "
        f"write the WHOLE analysis in {name}. 'class_level', 'heterogeneity', "
        "'notes' and every bullet of 'what_worked' / 'what_caused_problems' / "
        "'recommendations' are in "
        f"{name}. Verbatim student names / quotes / levels stay as given; "
        "'class_level_pill' value never changes."
    )


def build_class_insight_messages(*, assignment: dict, stats: dict,
                                 ui_language: Optional[str] = None) -> list[dict]:
    """Prompt for the per-assignment AI class insight ("Avis IA" on the Stats
    view): reads the assignment (instruction + document + repères via the
    evaluation notes), the per-student evaluations (levels + AI feedback
    summaries) and the per-class statistics, and produces a JSON class
    analysis (class level, heterogeneity, what worked, what caused problems)."""
    parts = []
    target = (assignment.get("target_level") or "").strip().upper()
    skill = assignment.get("skill") or ""
    kind = assignment.get("kind") or ""
    parts.append(
        "ASSIGNMENT (subject) being analyzed:\n"
        f"- Name: {assignment.get('name')}\n"
        + (f"- Expected target level: {target}\n" if target else "- Expected target level: not set\n")
        + (f"- Type: {skill} {kind}\n" if (skill or kind) else "")
    )
    instr = (assignment.get("instruction") or "").strip()
    doc = (assignment.get("document_text") or "").strip()
    if instr:
        if len(instr) > DOC_CHAR_CAP:
            instr = instr[:DOC_CHAR_CAP] + "\n[…instruction truncated…]"
        parts.append("ASSIGNMENT INSTRUCTION (what the students had to do — "
                     "part of the repères):\n" + instr)
    if doc:
        if len(doc) > DOC_CHAR_CAP:
            doc = doc[:DOC_CHAR_CAP] + "\n[…document truncated…]"
        parts.append("SOURCE DOCUMENT (the material the work is based on):\n" + doc)
    notes = (assignment.get("eval_notes") or "").strip()
    if notes:
        if len(notes) > DOC_CHAR_CAP:
            notes = notes[:DOC_CHAR_CAP] + "\n[…notes truncated…]"
        parts.append("TEACHER'S EVALUATION NOTES (the repères to check):\n" + notes)

    lv = {}
    for e in stats.get("evaluations_detail", []):
        c = e["classroom"]
        lv.setdefault(c, []).append(e["student"] + " → " + (e["overall"] or "—"))
    if lv:
        parts.append("OVERALL LEVELS PER CLASS (student → overall CEFR level):\n"
                     + "\n".join(f"- {c}: " + ", ".join(v) for c, v in lv.items()))

    lines = []
    for e in stats.get("evaluations_detail", []):
        entry = (f"- {e['student']} ({e['classroom']}): "
                 + " · ".join(f"{c} {lev or '—'}" for c, lev in e["criteria"].items())
                 + f" → overall {e['overall'] or '—'}")
        fb = e.get("feedback") or {}
        succ = (fb.get("key_success") or "").strip()
        tgt = (fb.get("target_area") or "").strip()
        com = (fb.get("comment") or "").strip()
        if succ or tgt or com:
            entry += ("\n    AI summary: "
                      + ("★ " + succ if succ else "")
                      + (" | ⌑ " + tgt if tgt else "")
                      + (" | " + com if com else ""))
        lines.append(entry)
    if lines:
        parts.append("THE " + str(len(lines))
                     + " EVALUATIONS (one per evaluated student; levels per "
                     "criterion from the grading rubric + the AI evaluation "
                     "summary of each student's work):\n" + "\n".join(lines))

    cl_blocks = []
    for cl in stats.get("by_class", []):
        rows = []
        for cname, d in sorted(cl.get("criterion", {}).items()):
            rows.append(f"    - {cname}: {_moment_line(d)}")
        ov = cl.get("overall") or {}
        rows.append(f"    - OVERALL: {_moment_line(ov)}")
        cl_blocks.append(f"CLASS {cl.get('classroom')} ({len(cl.get('students', []))} students):\n"
                         + "\n".join(rows))
    if cl_blocks:
        parts.append("STATISTICS PER CLASS (0–30 point scale: A1=1, A2=3, B1=5, "
                     "B2=10, C1=20, C2=30; μ=mean M=median σ=std-dev):\n"
                     + "\n".join(cl_blocks))

    ci_lang = class_insight_language_instruction(ui_language or "")
    ci_sys = language_system_line(ui_language or "")
    user = ("\n\n".join(parts)
            + ("\n\n" + ci_lang if ci_lang else "")
            + "\n\nProduce the CLASS ANALYSIS following the exact JSON schema "
              "below. Respond with ONLY a valid JSON object. No markdown fences, "
              "no prose before/after.\nJSON SCHEMA:\n" + CLASS_INSIGHT_SCHEMA)
    return [
        {"role": "system",
         "content": CLASS_INSIGHT_SYSTEM_PROMPT
                    + ("\n\n" + ci_sys if ci_sys else "")},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------- JSON parsing
REQUIRED_KEYS = {"executive_summary", "overall_level", "rubric_mapping", "student_feedback"}


# ------------------------------------------------- roster import prompt (2026-11-08)
ROSTER_IMPORT_SYSTEM_PROMPT = """You are an OCR assistant for a language teacher.
The user gives you one or several photos of the class's STUDENT ROSTER sheet
(liste des élèves) — the page(s) where the school wrote the class name, the
school name, and the students' first and last names, usually in a numbered
list or a table.

Your task: read every photo and produce ONE JSON object with the class
identity and every student you can find, exactly in the sheet's order.

Rules:
- First name and last name go in SEPARATE fields. A typical French-style
  sheet lists "Prénom NOM" — the last word is the surname.
- Transcribe names exactly as written, keeping accents and apostrophes
  (Éléonore, O'Brien, N'Guyen). Do NOT invent, complete or correct names:
  if a name is partly illegible, keep what is readable and note it in
  "warnings".
- One JSON object per student. If two photos show the same student twice,
  list them twice (the teacher will deduplicate).
- "class_name": the class designation visible on the sheet (e.g. "2G1",
  "L3", "Terminale STMG"). null when not visible.
- "school_name": the school / établissement name visible on the sheet.
  null when not visible.
- Do not include teachers, absentees marked "absent(e)", or header words in
  the student list.
- "warnings": short notes in the UI language for anything ambiguous
  (illegible letters, possible misreadings). Empty array when everything is
  clear.

Respond with ONLY a valid JSON object. No markdown fences, no prose
before/after.

JSON SCHEMA:
{
  "class_name": "string|null",
  "school_name": "string|null",
  "students": [
    { "first_name": "string", "last_name": "string" }
  ],
  "warnings": [ "string" ]
}
"""


def build_roster_import_messages(*, image_data_urls: list,
                                 ui_language: Optional[str] = None) -> list[dict]:
    """Prompt for the class-roster import: one LLM vision call over ALL the
    roster photos, returning class identity + student names as strict JSON."""
    lang_block = language_instruction(ui_language or "")
    user_text = ("These are photos of the class student-roster sheet "
                 f"({len(image_data_urls)} photo(s)). Extract the class "
                 "identity and every student name, in the sheet's order.")
    content: list = [{"type": "text", "text": user_text}]
    content += [{"type": "image_url", "image_url": {"url": url}}
                for url in image_data_urls]
    return [
        {"role": "system",
         "content": ROSTER_IMPORT_SYSTEM_PROMPT +
                    (("\n\n" + lang_block) if lang_block else "")},
        {"role": "user", "content": content},
    ]


def parse_result(text: str) -> dict:
    """Parse the model reply into a structured dict.

    Returns {ok: bool, data: dict|None, raw: str, error: str|None}.
    """
    from . import llm_client
    data = llm_client.extract_json(text)
    if isinstance(data, dict) and REQUIRED_KEYS.issubset(data.keys()):
        # normalise
        data.setdefault("strong_points", [])
        data.setdefault("areas_for_improvement", [])
        data.setdefault("fluency", {})
        if data.get("versus_target") not in ("meets", "below", "above"):
            data["versus_target"] = "n/a"
        return {"ok": True, "data": data, "raw": text, "error": None}
    # graceful fallback: treat whole thing as raw markdown
    return {"ok": False, "data": None, "raw": text,
            "error": "Model reply could not be parsed into the expected JSON schema; "
                     "showing raw response instead."}


def validate_matrix(data: dict, rubric: dict) -> list[str]:
    """Return a list of warnings (e.g. missing criteria)."""
    warnings = []
    want = {c["name"] for c in rubric["criteria"]}
    have = {m.get("criterion") for m in data.get("rubric_mapping", [])}
    for missing in want - have:
        warnings.append(f"Rubric criterion '{missing}' has no mapping.")
    # evidence check: every mapping should carry >=1 evidence item
    for m in data.get("rubric_mapping", []):
        if not m.get("evidence"):
            warnings.append(f"'{m.get('criterion')}' is missing evidence.")
    return warnings
