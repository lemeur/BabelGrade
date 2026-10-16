#!/usr/bin/env python3
"""Probe the local SGLang qwen38-27b endpoint: text-only + vision (image) + audio."""
import base64, io, json, sys, time, urllib.request, os

BASE = os.environ.get("LLM_BASE", "http://127.0.0.1:8078/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen38-27b")

def call(messages, label, extra=None):
    body = {"model": MODEL, "messages": messages, "temperature": 0.1,
            "max_tokens": 400, "stream": False}
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
        dt = time.time() - t0
        msg = data["choices"][0]["message"]
        text = msg.get("content") or ""
        usage = data.get("usage", {})
        print(f"\n=== {label} ({dt:.1f}s) ===")
        print("OK. usage:", usage)
        print("reply:", text[:500])
        return True
    except Exception as e:
        print(f"\n=== {label} === ERROR: {type(e).__name__}: {e}")
        return False

def make_test_png():
    """Try to make a text image with PIL; fall back to solid color otherwise."""
    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 120), "white")
        d = ImageDraw.Draw(im)
        d.text((20, 40), "The cat sat on the mat.", fill="black")
        buf = io.BytesIO(); im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        # 1x1 red png fallback (PIL missing) - still tests the image code path
        tiny = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        print("PIL not available, using 1x1 fallback png:", e)
        return "data:image/png;base64," + base64.b64encode(tiny).decode()

print("BASE:", BASE, "MODEL:", MODEL)

# 1. text-only
call([
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": "Reply with exactly: TEXT_OK"},
], "TEXT")

# 2. vision
data_url = make_test_png()
call([
    {"role": "user", "content": [
        {"type": "text", "text": "What text is visible in this image? Reply exactly what you read."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]},
], "VISION")

# 3. audio (probe whether content type is accepted)
tiny_wav = base64.b64decode(
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=")  # empty wav header
data_url_audio = "data:audio/wav;base64," + base64.b64encode(tiny_wav).decode()
call([
    {"role": "user", "content": [
        {"type": "text", "text": "Transcribe this audio."},
        {"type": "input_audio", "input_audio": {"data": data_url_audio, "format": "wav"}},
    ]},
], "AUDIO")
