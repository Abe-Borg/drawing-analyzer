"""Native, one-scroll dossier renderer, using the app's existing palette.

Tk dialogs use native toplevel labels/transient relationships, rather than web
ARIA attributes. Focus and stack ownership remain in gui.py. Content and the
SVG come from trust_dossier; no assets or network are loaded here.
"""
from __future__ import annotations

from .colors import COLORS
from . import trust_dossier as content


class DossierView:
    def __init__(self, master, on_close):
        # Keep tkinter out of the content/API import path.
        import tkinter as tk
        import customtkinter as ctk

        self._tk = tk
        self.frame = ctk.CTkFrame(master, fg_color=COLORS["bg_dark"])
        self.frame.pack(fill="both", expand=True)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=1)
        self.rail = ctk.CTkFrame(self.frame, fg_color=COLORS["bg_card"], width=215)
        self.rail.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.text = tk.Text(
            self.frame, wrap="word", background=COLORS["bg_dark"],
            foreground=COLORS["text_secondary"], insertbackground=COLORS["text_primary"],
            relief="flat", borderwidth=0, padx=16, pady=12,
            font=("Segoe UI", 12), spacing3=9, takefocus=True,
            selectbackground=COLORS["accent"], selectforeground=COLORS["text_primary"],
        )
        self.text.grid(row=0, column=1, sticky="nsew")
        self.scrollbar = ctk.CTkScrollbar(self.frame, command=self.text.yview)
        self.scrollbar.grid(row=0, column=2, sticky="ns")
        self.text.configure(yscrollcommand=self._scrolled)
        for name, options in {
            "kicker": {"foreground": COLORS["accent_glow"], "font": ("Segoe UI", 11)},
            "heading": {"foreground": COLORS["text_primary"], "font": ("Segoe UI", 19, "bold"), "spacing1": 24},
            "title": {"foreground": COLORS["text_primary"], "font": ("Segoe UI", 13, "bold"), "spacing1": 14},
            "label": {"foreground": COLORS["text_primary"], "font": ("Segoe UI", 12, "bold")},
            "note": {"background": COLORS["bg_card"], "lmargin1": 14, "lmargin2": 14, "rmargin": 14},
            "card": {"background": COLORS["bg_card"], "lmargin1": 14, "lmargin2": 14, "rmargin": 14},
        }.items():
            self.text.tag_configure(name, **options)
        self.buttons = []
        self.links = []
        self.windows = []
        self.marks = []
        self.current = None
        self._last_width = 0
        tk.Label(self.rail, text="Contents", font=("Segoe UI", 13, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_primary"]).pack(anchor="w", padx=12, pady=12)
        for section in content.sections():
            mark = "section_" + section.id
            self.text.mark_set(mark, "end-1c")
            self.text.mark_gravity(mark, "left")
            self.marks.append(mark)
            button = self._button(self.rail, section.kicker,
                                  lambda m=mark: self.jump(m), wraplength=190)
            button.pack(fill="x", padx=6, pady=2)
            self.buttons.append(button)
            self.text.insert("end", section.kicker + "\n", "kicker")
            self.text.insert("end", section.title + "\n", "heading")
            for block in section.blocks:
                self._block(block)
            self.text.insert("end", "\n")
        self.text.configure(state="disabled")
        self.frame.bind("<Configure>", self._resize, add="+")
        self.text.bind("<Configure>", self._resize_content, add="+")
        self.frame.after_idle(self._resize_content)
        self.focus_targets = [*self.buttons, self.text, *self.links]

    def _button(self, master, text, command, **kwargs):
        return self._tk.Button(
            master, text=text, command=command, anchor="w", justify="left",
            bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
            activebackground=COLORS["bg_input"], activeforeground=COLORS["text_primary"],
            highlightbackground=COLORS["border"], highlightcolor=COLORS["accent_glow"],
            highlightthickness=2, relief="flat", borderwidth=0,
            font=("Segoe UI", 11), takefocus=True, **kwargs,
        )

    def jump(self, mark):
        self.text.yview(mark)
        self.text.mark_set("insert", mark)
        self.text.focus_set()
        self._update_current()

    def _scrolled(self, first, last):
        self.scrollbar.set(first, last)
        if hasattr(self, "marks"):
            self._update_current()

    def _update_current(self):
        first = self.text.index("@0,0")
        current = 0
        for i, mark in enumerate(self.marks):
            if self.text.compare(mark, "<=", first):
                current = i
        if current == self.current:
            return
        self.current = current
        for i, button in enumerate(self.buttons):
            button.configure(fg=COLORS["accent_glow"] if i == current else COLORS["text_secondary"],
                             bg=COLORS["bg_input"] if i == current else COLORS["bg_card"])

    def _resize(self, event=None):
        if self.frame.winfo_width() < 900:
            self.rail.grid_remove()
        else:
            self.rail.grid()

    def _resize_content(self, event=None):
        width = max(180, self.text.winfo_width() - 42)
        if width == self._last_width:
            return
        self._last_width = width
        for widget, labels, columns in self.windows:
            # Off-screen Text windows do not always get a geometry pass. Set
            # their size explicitly so a previously wide table cannot retain
            # its old requested width when it scrolls into a narrow viewport.
            widget.grid_propagate(False)
            narrow = width < 580
            for index, label in enumerate(labels):
                label.grid_forget()
                label.grid(row=index if narrow else index // columns,
                           column=0 if narrow else index % columns, sticky="nsew", padx=3, pady=3)
                label.configure(wraplength=width - 24 if narrow else max(90, width // columns - 24))
            for col in range(columns):
                widget.grid_columnconfigure(col, weight=1 if (not narrow or col == 0) else 0)
            row_heights = {}
            for index, label in enumerate(labels):
                row = index if narrow else index // columns
                row_heights[row] = max(row_heights.get(row, 0), label.winfo_reqheight() + 6)
            widget.configure(width=width, height=sum(row_heights.values()))
        # Redraw the same inline SVG at the text viewport's width.
        for canvas in getattr(self, "diagrams", []):
            self._draw_svg(canvas, width)

    def _embed(self, widget, labels=(), columns=1):
        self.text.window_create("end", window=widget)
        self.text.insert("end", "\n")
        if labels:
            self.windows.append((widget, labels, columns))

    def _table(self, block):
        tk = self._tk
        frame = tk.Frame(self.text, bg=COLORS["border"])
        labels = []
        for row_index, row in enumerate((block.headers, *block.rows)):
            for col_index, value in enumerate(row):
                label = tk.Label(
                    frame, text=value, anchor="nw", justify="left", padx=8, pady=8,
                    bg=COLORS["bg_input"] if row_index == 0 else COLORS["bg_card"],
                    fg=COLORS["text_primary"] if row_index == 0 else COLORS["text_secondary"],
                    font=("Segoe UI", 11, "bold") if row_index == 0 else ("Segoe UI", 11),
                    wraplength=200,
                )
                label.grid(row=row_index, column=col_index, sticky="nsew", padx=3, pady=3)
                labels.append(label)
        self._embed(frame, labels, len(block.headers))

    def _block(self, block):
        tk = self._tk
        if isinstance(block, content.Table):
            self._table(block)
        elif isinstance(block, content.Diagram):
            canvas = tk.Canvas(self.text, bg=COLORS["bg_dark"], highlightthickness=0)
            self.diagrams = getattr(self, "diagrams", []) + [canvas]
            self._draw_svg(canvas, 600)
            self._embed(canvas)
            # Native readable equivalent of SVG aria-label, available as text.
            self.text.insert("end", block.description + "\n")
        elif isinstance(block, content.Runtime):
            self.text.mark_set(block.id, "end-1c")
            self.text.mark_gravity(block.id, "left")
            self.text.insert("end", block.id + " · " + block.title + "\n", ("title", "card"))
            for label, value in block.rows:
                self.text.insert("end", label + ": ", ("label", "card"))
                self.text.insert("end", value + "\n", "card")
            self.text.insert("end", "\n")
        elif isinstance(block, content.Note):
            self.text.insert("end", block.title + "\n", ("title", "note"))
            self.text.insert("end", block.text + "\n", "note")
        elif isinstance(block, content.Bullets):
            for item in block.items:
                self.text.insert("end", "• " + item + "\n")
        elif isinstance(block, content.Contrast):
            self._table(content.Table(("Leaves your machine", "Stays on your machine"), ((block.leaves, block.stays),), block.refs))
        elif isinstance(block, content.Links):
            import webbrowser
            self.text.insert("end", "Further reading\n", "title")
            frame = tk.Frame(self.text, bg=COLORS["bg_dark"])
            labels = []
            for label, url in block.items:
                button = self._button(frame, label, lambda u=url: webbrowser.open(u))
                button.pack(fill="x")
                labels.append(button)
            self.links.extend(labels)
            self._embed(frame)
        else:
            self.text.insert("end", block.text + "\n")

    @staticmethod
    def _draw_svg(canvas, width):
        # Interpret just the fixed trusted diagram's inline shapes. XML parsing
        # does not resolve external resources and this SVG has no href/image/use.
        from xml.etree import ElementTree
        canvas.delete("all")
        scale = width / 720
        canvas.configure(width=width, height=360 * scale)
        for element in ElementTree.fromstring(content.BOUNDARY_SVG):
            tag = element.tag.rsplit("}", 1)[-1]
            a = element.attrib
            coord = lambda name: float(a[name]) * scale
            color = COLORS["text_secondary"]
            if tag == "rect":
                x, y = coord("x"), coord("y")
                canvas.create_rectangle(x, y, x + coord("width"), y + coord("height"), outline=color)
            elif tag == "line":
                canvas.create_line(coord("x1"), coord("y1"), coord("x2"), coord("y2"), fill=color,
                                   dash=(6, 4) if "stroke-dasharray" in a else ())
            elif tag == "text":
                canvas.create_text(coord("x"), coord("y"), anchor="sw", text=element.text,
                                   fill=COLORS["text_primary"], font=("Segoe UI", max(7, round(11 * scale))))
