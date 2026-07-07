"""
Tkinter 自定义审批弹窗（子进程模式）
通过 CLI 参数配置，JSON 输出结果，供 server.py 调用。
"""
import sys
import json
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk

sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent  # project root
_RESULT = {"status": "cancelled", "value": ""}
_CONFIG = {}


def _load_config(locale: str) -> dict:
    path = _SCRIPT_DIR / "locale" / f"{locale}.json"
    if not path.exists():
        path = _SCRIPT_DIR / "locale" / "en.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--locale", default="en")
    p.add_argument("--title", default="")
    p.add_argument("--message", required=True)
    p.add_argument("--type", default="confirm", choices=["confirm", "input", "ua", "inquiry"])
    p.add_argument("--options", default="")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--default", default="")
    p.add_argument("--questions", default="")
    p.add_argument("--other", default="disable")
    p.add_argument("--remarks", default="disable")
    p.add_argument("--inquiry_type", default="single_question")
    return p.parse_args()


def _build_ui(root, title, message, options, timeout, default_label, cfg):
    ui = cfg["ui"]
    st = cfg["style"]
    font_family = st["font_family"]

    seconds_left = [max(timeout, 0)]
    default_idx = options.index(default_label) if default_label in options else 0

    root.title(title or ui["default_title"])
    root.attributes("-topmost", True)
    root.resizable(False, False)

    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    frame = ttk.Frame(root, padding=(st["frame_padding_h"], st["frame_padding_v"]))
    frame.pack(fill="both", expand=True)

    msg = ttk.Label(
        frame, text=message, wraplength=st["message_wraplength"],
        justify="left", font=(font_family, st["message_font_size"]),
    )
    msg.pack(pady=(0, st["message_pady"]))

    if timeout > 0:
        timer = ttk.Label(
            frame,
            text=ui["timeout_pattern"].format(seconds=timeout),
            foreground=st["timer_foreground"],
            font=(font_family, st["timer_font_size"]),
        )
        timer.pack(pady=(0, st["timer_pady"]))
    else:
        timer = None

    btn_frame = ttk.Frame(frame)
    btn_frame.pack()

    def _on_click(idx, label):
        _RESULT["status"] = "selected"
        _RESULT["value"] = label
        root.destroy()

    def _on_cancel():
        root.destroy()

    for i, label in enumerate(options):
        is_default = i == default_idx
        btn = ttk.Button(
            btn_frame, text=label, width=st["button_width"],
            command=lambda idx=i, lbl=label: _on_click(idx, lbl),
            default="active" if is_default else "normal",
        )
        btn.pack(side="left", padx=st["button_padx"])
        if is_default:
            btn.focus_set()

    root.protocol("WM_DELETE_WINDOW", _on_cancel)
    root.bind("<Escape>", lambda e: _on_cancel())
    root.bind("<Return>", lambda e: _on_click(default_idx, options[default_idx]))

    if timeout > 0 and timer:

        def _tick():
            seconds_left[0] -= 1
            if seconds_left[0] <= 0:
                _RESULT["status"] = "timeout"
                root.destroy()
            else:
                timer.config(text=ui["timeout_pattern"].format(seconds=seconds_left[0]))
                root.after(1000, _tick)

        root.after(1000, _tick)


def _build_inquiry(root, title, message, questions_json, timeout, inquiry_type,
                    other_enabled, remarks_enabled, cfg):
    ui = cfg["ui"]
    st = cfg["style"]
    font_family = st["font_family"]
    seconds_left = [max(timeout, 0)]

    root.title(title or ui["default_title"])
    root.attributes("-topmost", True)
    root.minsize(520, 300)

    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    questions = json.loads(questions_json) if questions_json else []

    canvas = tk.Canvas(root, highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scroll_frame = ttk.Frame(canvas)
    scroll_frame.bind(
        "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    msg = ttk.Label(
        scroll_frame, text=message, wraplength=480,
        justify="left", font=(font_family, st["message_font_size"]),
    )
    msg.pack(anchor="w", pady=(0, 14))

    canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(16, 0))
    scrollbar.pack(side="right", fill="y", pady=(16, 0))

    entries = []
    bottom_frame = ttk.Frame(root)

    sep = ttk.Separator(scroll_frame, orient="horizontal")
    sep.pack(fill="x", pady=(0, 10))

    for idx, item in enumerate(questions):
        q_text = item.get("q", "")
        opts = item.get("options", [])

        q_label = ttk.Label(
            scroll_frame,
            text=f"{idx + 1}. {q_text}",
            wraplength=480, justify="left",
            font=(font_family, st["message_font_size"]),
        )
        q_label.pack(anchor="w", pady=(6, 4))

        if inquiry_type in ("multiple_options",) and opts:
            var = tk.StringVar(value=opts[0])
            combo = ttk.Combobox(
                scroll_frame, textvariable=var, values=opts,
                state="readonly", font=(font_family, st["message_font_size"]),
            )
            combo.pack(anchor="w", pady=(0, 4))
            entries.append({"q": q_text, "widget": combo, "var": var, "opts": opts, "idx": idx})
        else:
            var = tk.StringVar()
            entry = ttk.Entry(
                scroll_frame, textvariable=var,
                font=(font_family, st["message_font_size"]),
            )
            entry.pack(anchor="w", fill="x", pady=(0, 4))
            entries.append({"q": q_text, "widget": entry, "var": var, "idx": idx})

        if other_enabled:
            other_var = tk.StringVar()
            other_entry = ttk.Entry(
                scroll_frame,
                font=(font_family, 9),
            )
            other_label = ttk.Label(
                scroll_frame, text=ui["inquiry_other_label"],
                font=(font_family, 9), foreground=st["timer_foreground"],
            )
            other_label.pack(anchor="w")
            other_entry.pack(anchor="w", fill="x", pady=(0, 8))
            entries.append({"q": f"{q_text}（{ui['inquiry_other_label']}）", "widget": other_entry, "var": other_var, "idx": idx, "other": True})

    if remarks_enabled:
        sep2 = ttk.Separator(scroll_frame, orient="horizontal")
        sep2.pack(fill="x", pady=(8, 6))
        remarks_label = ttk.Label(
            scroll_frame, text=ui["inquiry_remarks_label"],
            font=(font_family, st["message_font_size"]),
        )
        remarks_label.pack(anchor="w", pady=(0, 4))
        remarks_var = tk.StringVar()
        remarks_entry = ttk.Entry(
            scroll_frame, textvariable=remarks_var,
            font=(font_family, st["message_font_size"]),
        )
        remarks_entry.pack(anchor="w", fill="x", pady=(0, 8))
        entries.append({"q": ui["inquiry_remarks_key"], "widget": remarks_entry, "var": remarks_var, "idx": -1, "remarks": True})

    btn_frame = ttk.Frame(bottom_frame)
    btn_frame.pack(pady=(8, 10))

    def _on_submit():
        lines = []
        grouped = {}
        for e in entries:
            key = e["q"]
            val = e["var"].get().strip()
            if not val:
                continue
            if key in grouped:
                grouped[key] += f"；{ui['inquiry_supplement_prefix']}{val}"
            else:
                grouped[key] = val
        for q, v in grouped.items():
            lines.append(f"{q} → {v}")
        _RESULT["status"] = "submitted"
        _RESULT["value"] = "\n".join(lines)
        root.destroy()

    def _on_cancel():
        root.destroy()

    submit_btn = ttk.Button(btn_frame, text=ui["submit"], command=_on_submit, width=st["submit_button_width"])
    submit_btn.pack(side="left", padx=st["button_padx"])
    cancel_btn = ttk.Button(btn_frame, text=ui["cancel"], command=_on_cancel, width=st["submit_button_width"])
    cancel_btn.pack(side="left", padx=st["button_padx"])

    bottom_frame.pack(side="bottom", fill="x")

    timer_label = ttk.Label(bottom_frame, text="", foreground=st["timer_foreground"],
                            font=(font_family, st["timer_font_size"]))
    if timeout > 0:
        timer_label.config(text=ui["timeout_pattern"].format(seconds=timeout))
        timer_label.pack(pady=(0, 4))
    else:
        timer_label.pack_forget()

    root.protocol("WM_DELETE_WINDOW", _on_cancel)
    root.bind("<Escape>", lambda e: _on_cancel())

    if entries:
        w = entries[0]["widget"]
        if hasattr(w, "focus_set"):
            w.focus_set()

    if timeout > 0:

        def _tick():
            seconds_left[0] -= 1
            if seconds_left[0] <= 0:
                _RESULT["status"] = "timeout"
                root.destroy()
            else:
                timer_label.config(text=ui["timeout_pattern"].format(seconds=seconds_left[0]))
                root.after(1000, _tick)

        root.after(1000, _tick)


def _build_input(root, title, message, timeout, default_text, cfg):
    ui = cfg["ui"]
    st = cfg["style"]
    font_family = st["font_family"]

    seconds_left = [max(timeout, 0)]

    root.title(title or ui["default_title"])
    root.attributes("-topmost", True)
    root.resizable(False, False)

    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    frame = ttk.Frame(root, padding=(st["frame_padding_h"], st["frame_padding_v"]))
    frame.pack(fill="both", expand=True)

    msg = ttk.Label(
        frame, text=message, wraplength=st["message_wraplength"],
        justify="left", font=(font_family, st["message_font_size"]),
    )
    msg.pack(pady=(0, st["message_input_pady"]))

    entry_var = tk.StringVar(value=default_text)
    entry = ttk.Entry(
        frame, textvariable=entry_var,
        font=(font_family, st["message_font_size"]), width=st["entry_width"],
    )
    entry.pack(pady=(0, st["entry_pady"]))
    entry.focus_set()
    entry.selection_range(0, "end")

    if timeout > 0:
        timer = ttk.Label(
            frame,
            text=ui["timeout_pattern"].format(seconds=timeout),
            foreground=st["timer_foreground"],
            font=(font_family, st["timer_font_size"]),
        )
        timer.pack(pady=(0, st["timer_input_pady"]))
    else:
        timer = None

    btn_frame = ttk.Frame(frame)
    btn_frame.pack()

    def _on_submit():
        _RESULT["status"] = "submitted"
        _RESULT["value"] = entry_var.get().strip()
        root.destroy()

    def _on_cancel():
        root.destroy()

    submit_btn = ttk.Button(btn_frame, text=ui["submit"], command=_on_submit, width=st["submit_button_width"])
    submit_btn.pack(side="left", padx=st["button_padx"])

    cancel_btn = ttk.Button(btn_frame, text=ui["cancel"], command=_on_cancel, width=st["submit_button_width"])
    cancel_btn.pack(side="left", padx=st["button_padx"])

    root.protocol("WM_DELETE_WINDOW", _on_cancel)
    root.bind("<Return>", lambda e: _on_submit())
    root.bind("<Escape>", lambda e: _on_cancel())

    if timeout > 0 and timer:

        def _tick():
            seconds_left[0] -= 1
            if seconds_left[0] <= 0:
                _RESULT["status"] = "timeout"
                root.destroy()
            else:
                timer.config(text=ui["timeout_pattern"].format(seconds=seconds_left[0]))
                root.after(1000, _tick)

        root.after(1000, _tick)


def main():
    args = _parse_args()
    cfg = _load_config(args.locale)
    timeout = args.timeout if args.timeout > 0 else 0
    ui = cfg["ui"]

    root = tk.Tk()

    if args.type == "input":
        _build_input(root, args.title, args.message, timeout, args.default, cfg)
    elif args.type == "inquiry":
        other_enabled = args.other == "enable"
        remarks_enabled = args.remarks == "enable"
        _build_inquiry(root, args.title, args.message, args.questions,
                       timeout, args.inquiry_type, other_enabled, remarks_enabled, cfg)
    else:
        options = [c.strip() for c in (args.options or ui["default_options"]).split(",") if c.strip()]
        if not options:
            print(json.dumps({"status": "error", "value": ui["error_no_options"]}))
            sys.exit(1)
        _build_ui(root, args.title, args.message, options, timeout, args.default, cfg)

    root.update_idletasks()
    w = root.winfo_reqwidth()
    h = root.winfo_reqheight()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
    print(json.dumps(_RESULT, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
