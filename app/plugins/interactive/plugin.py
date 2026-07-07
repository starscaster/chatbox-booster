"""
Interactive plugin — user interaction dialogs via Tkinter subprocess.

Migrated from server.py interactive dialog functions.
Uses approve_dialog.py as a subprocess for GUI dialogs.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _parse_inquiry_items(inquiries: str, inquiry_type: str):
    """Parse inquiry items from text. Same logic as original server.py."""
    text = inquiries.strip()
    q_pattern = re.compile(
        r"(?:^|\n)\s*(?:\d+[\u2063\u278a-\u279f\u2460-\u2473]"
        r"|\d+\s*[\.、．。)]\s*"
        r"|[\u2460-\u2473]\s*"
        r"|[A-Fa-f]\s*[\.、．)]\s*)"
        r"(?:\*{1,2}(.+?)\*{1,2}|(.+?))"
        r"(?=(?:\n\s*(?:\d+[\u2063\u278a-\u279f\u2460-\u2473]"
        r"|\d+\s*[\.、．。)]"
        r"|[\u2460-\u2473]"
        r"|[A-Fa-f]\s*[\.、．)])|\n\s*$|\Z))",
        re.DOTALL,
    )
    raw = q_pattern.findall(text)
    if not raw:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) <= 1:
            return [{"q": text.strip()}]
        items = []
        for line in lines:
            line = re.sub(r"^[#\-\*\s]+", "", line).strip()
            line = re.sub(r"\*{1,2}", "", line)
            if line:
                items.append({"q": line})
        return items or [{"q": text.strip()}]
    items = []
    for bold, plain in raw:
        q = (bold or plain).strip()
        q = re.sub(r"^[：:]\s*", "", q)
        q = re.sub(r"\s+", " ", q)
        items.append({"q": q})
    if inquiry_type == "multiple_options":
        opt_pattern = re.compile(r"[A-Fa-f]\s*[\.、．)]\s*(.+?)(?=\s*[A-Fa-f]\s*[\.、．)]|\s*$)", re.DOTALL)
        for item in items:
            opts = opt_pattern.findall(item["q"])
            opts = [o.strip().rstrip(";；,") for o in opts if o.strip()]
            if opts:
                main = re.sub(r"[A-Fa-f]\s*[\.、．)].*$", "", item["q"]).strip()
                main = re.sub(r"[：:]\s*$", "", main)
                item["q"] = main
                item["options"] = opts
    return items


def _invoke_dialog(extra_args: list, timeout: int, ctx) -> str:
    L = ctx.locale_section("server")
    dialog_script = Path(__file__).resolve().parent / "approve_dialog.py"
    if not dialog_script.exists():
        return L.get("script_missing")
    locale_code = ctx.locale_code
    cmd = [sys.executable, str(dialog_script), "--locale", locale_code] + extra_args
    popen_env = os.environ.copy()
    popen_env.setdefault("PYTHONIOENCODING", "utf-8")
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": popen_env,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except Exception as exc:
        return L.get("start_failed", error=exc)
    try:
        out, err = proc.communicate(timeout=(timeout + 15) if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return L.get("timeout", timeout=timeout)
    output = (out or "").strip()
    if not output:
        return L.get("no_response", stderr=(err or "").strip() or L.get("no_output"))
    try:
        payload = json.loads(output.splitlines()[-1])
    except json.JSONDecodeError:
        return L.get("invalid_response", raw=output[:200])
    status = payload.get("status")
    value = str(payload.get("value", "")).strip()
    if status == "timeout":
        return L.get("timeout", timeout=timeout)
    if status == "cancelled":
        return L.get("cancelled")
    if status == "selected":
        return L.get("selected", value=value) if value else L.get("confirmed")
    if status == "submitted":
        return value if value else L.get("submitted_empty")
    if status == "error":
        return L.get("dialog_error", value=(value or L.get("unknown")))
    return L.get("unknown", data=payload)


def register(ctx):
    def interactive_dialog_UA(title: str, message: str, timeout: int = 120, default: str = "no") -> str:
        """
        User approval dialog with Yes/No/Cancel buttons.
        Use for sensitive operation confirmation.

        Args:
            title: Window title.
            message: Prompt content.
            timeout: Timeout in seconds (default 120).
            default: Default focused button (default "no").
        """
        return _invoke_dialog(
            ["--type", "ua", "--title", title, "--message", message,
             "--timeout", str(timeout), "--default", default],
            timeout, ctx,
        )

    def interactive_dialog_input(title: str, message: str, timeout: int = 120, default: str = "") -> str:
        """
        Single-line text input dialog.
        Use to collect brief information from the user.

        Args:
            title: Window title.
            message: Prompt content.
            timeout: Timeout in seconds (default 120).
            default: Pre-filled text (default empty).
        """
        return _invoke_dialog(
            ["--type", "input", "--title", title, "--message", message,
             "--timeout", str(timeout), "--default", default],
            timeout, ctx,
        )

    def interactive_dialog_inquiry(
        title: str,
        message: str,
        timeout: int = 300,
        default: str = "",
        inquires: str = "",
        inquiry_type: str = "single_question",
        other: str = "disable",
        remarks: str = "disable",
    ) -> str:
        """
        Structured information collection form.
        Auto-parses questions from the inquires string.

        Args:
            title: Window title.
            message: Prompt description (display only).
            timeout: Timeout in seconds (default 300).
            default: Pre-filled default (first question only).
            inquires: Question description. Supports auto-splitting formats.
            inquiry_type: single_question / multiple_question / multiple_options.
            other: enable = add "other" input per question.
            remarks: enable = add remarks input at end.
        """
        source = inquires or message
        questions = _parse_inquiry_items(source, inquiry_type)
        questions_json = json.dumps(questions, ensure_ascii=False)
        return _invoke_dialog(
            ["--type", "inquiry", "--title", title, "--message", message,
             "--timeout", str(timeout), "--default", default,
             "--questions", questions_json, "--other", other,
             "--remarks", remarks, "--inquiry_type", inquiry_type],
            timeout, ctx,
        )

    return [interactive_dialog_UA, interactive_dialog_input, interactive_dialog_inquiry]