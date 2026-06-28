#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tcl/Tk front-end for the annuity-equivalent Monte Carlo (montecarlo.py).

The top portion collects the same inputs as the command line; inputs with a
fixed set of choices (gender, state, joint gender, model, quotes source) are
drop-downs. Tab moves the focus through every input and the Submit button in
order; pressing Enter while the Submit button has focus runs the simulation, so
no mouse is needed. The simulation runs on a background thread to keep the
window responsive while it builds the annuity-rate cache (local pricing by
default; "site" warms it over the network).

Below the report there are Export PDF, Export CSV, and Exit buttons. "Export PDF"
renders the single consolidated report in report_pdf.py (summary cards, the
balance fan chart, median/stress scenario charts, and the per-year table);
"Export CSV" reuses montecarlo.write_csv. Both act on the most recent run. A row
of Docs buttons opens the bundled README / methodology / fit-notes documents in
the OS default viewer, independent of any run.

Run with a Python that has tkinter (the project .venv does):
    ~/finance/planning/.venv/bin/python montecarlo_gui.py
"""

from __future__ import annotations

import argparse
import os
import pathlib
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

import annuity_quote
import montecarlo as mc

# Directory holding this script and its sibling documentation files.
_HERE = pathlib.Path(__file__).resolve().parent

# Documentation files reachable from the Docs buttons: (label, filename).
_DOCS = [
    ("README", "README.html"),
    ("Methodology", "METHODOLOGY.pdf"),
    ("Fit notes", "FIT.pdf"),
]


def _open_file(path: pathlib.Path):
    """Open a file in the OS default application."""
    if sys.platform.startswith("darwin"):
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _optional(text):
    """Strip a field; return None when blank."""
    text = text.strip()
    return text or None


def _float_or_zero(widget):
    """Read a numeric entry, treating a blank field as 0."""
    text = widget.get().strip()
    return float(text) if text else 0.0


class MonteCarloGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Annuity-equivalent Monte Carlo")

        self._queue: queue.Queue = queue.Queue()
        self._last_csv_kwargs = None
        self._last_report_data = None

        mono = font.nametofont("TkFixedFont").copy()
        mono.configure(size=9)
        self._mono = mono

        self._build_inputs()
        self._build_output()
        self._build_actions()

        self.amount.focus_set()

    # ----- layout -----------------------------------------------------------
    def _build_inputs(self):
        frm = ttk.LabelFrame(self.root, text="Inputs", padding=8)
        frm.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        for c in (1, 3):
            frm.columnconfigure(c, weight=1)

        def row(r, c, label):
            ttk.Label(frm, text=label).grid(row=r, column=c, sticky="w",
                                            padx=(0, 4), pady=2)

        def entry(r, c, default=""):
            e = ttk.Entry(frm, width=16)
            e.insert(0, default)
            e.grid(row=r, column=c + 1, sticky="ew", padx=(0, 12), pady=2)
            return e

        def combo(r, c, values, default):
            cb = ttk.Combobox(frm, values=values, state="readonly", width=14)
            cb.set(default)
            cb.grid(row=r, column=c + 1, sticky="ew", padx=(0, 12), pady=2)
            return cb

        # Left column then right column, so Tab order reads top-to-bottom,
        # left-to-right naturally (widgets are created in that order).
        row(0, 0, "Amount"); self.amount = entry(0, 0, "1,000,000")
        row(0, 2, "Sims"); self.sims = entry(0, 2, "5000")

        row(1, 0, "Age"); self.age = entry(1, 0, "65")
        row(1, 2, "Years"); self.years = entry(1, 2, "35")

        row(2, 0, "Gender"); self.gender = combo(2, 0, ["M", "F"], "M")
        row(2, 2, "Model")
        self.model = combo(2, 2, ["us", "global", "postwar"], "global")

        row(3, 0, "State")
        self.state = combo(3, 0, sorted(annuity_quote.STATES), "FL")
        row(3, 2, "Block length"); self.block_length = entry(3, 2, "5")

        row(4, 0, "Joint age"); self.joint_age = entry(4, 0, "65")
        row(4, 2, "Upper bound"); self.upper_bound = entry(4, 2, "1.5")

        row(5, 0, "Joint gender")
        self.joint_gender = combo(5, 0, ["", "M", "F"], "F")
        row(5, 2, "Lower bound"); self.lower_bound = entry(5, 2, "")

        row(6, 0, "Seed"); self.seed = entry(6, 0, "42")
        row(6, 2, "Inflation")
        self.inflation = entry(6, 2, "")

        row(7, 0, "Quotes")
        self.quotes = combo(7, 0, ["local", "site"], mc.wp.DEFAULT_QUOTES)
        # One rate field: the fixed discount rate when static, or the starting
        # rate when dynamic (the model evolves it from there). A blank reads as 0.
        row(7, 2, "Interest rate")
        self.interest = entry(7, 2, str(mc.rate_model.DEFAULT_INITIAL_RATE))

        self.dynamic = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Dynamic inflation + rate (US sample, local only)",
                        variable=self.dynamic).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=2)

        self.improvement = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Scale G2 mortality improvement (local only)",
                        variable=self.improvement).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=2)

        self.submit = ttk.Button(frm, text="Submit", command=self.on_submit)
        self.submit.grid(row=9, column=3, sticky="e", padx=(0, 12), pady=(6, 2))
        # Enter on the focused Submit button runs the simulation.
        self.submit.bind("<Return>", lambda _e: self.on_submit())

        self.status = ttk.Label(frm, text="Ready.")
        self.status.grid(row=10, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_output(self):
        frm = ttk.Frame(self.root, padding=(8, 0))
        frm.grid(row=1, column=0, sticky="nsew", padx=8)
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self.output = tk.Text(frm, wrap="none", font=self._mono,
                              width=110, height=28)
        self.output.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(frm, orient="vertical", command=self.output.yview)
        ys.grid(row=0, column=1, sticky="ns")
        xs = ttk.Scrollbar(frm, orient="horizontal", command=self.output.xview)
        xs.grid(row=1, column=0, sticky="ew")
        self.output.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.output.configure(state="disabled")
        # Keep the report read-only but Tab-traversable past it.
        self.output.configure(takefocus=0)

    def _build_actions(self):
        frm = ttk.Frame(self.root, padding=8)
        frm.grid(row=2, column=0, sticky="ew")
        self.export_pdf = ttk.Button(frm, text="Export PDF",
                                     command=self.on_export_pdf, state="disabled")
        self.export_csv = ttk.Button(frm, text="Export CSV",
                                     command=self.on_export_csv, state="disabled")
        exit_btn = ttk.Button(frm, text="Exit", command=self.root.destroy)
        self.export_pdf.pack(side="left")
        self.export_csv.pack(side="left", padx=(8, 0))
        exit_btn.pack(side="right")

        # Documentation buttons: always available, independent of any run.
        ttk.Separator(frm, orient="vertical").pack(side="left", fill="y",
                                                    padx=10)
        ttk.Label(frm, text="Docs:").pack(side="left", padx=(0, 4))
        for label, filename in _DOCS:
            ttk.Button(
                frm, text=label, width=11,
                command=lambda fn=filename: self.on_open_doc(fn),
            ).pack(side="left", padx=(0, 4))

    # ----- helpers -----------------------------------------------------------
    def _set_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def _collect_params(self):
        """Validate the form and return a kwargs dict for montecarlo.build_report.

        Raises argparse.ArgumentTypeError / ValueError with a user-facing message.
        """
        amount = annuity_quote._normalize_amount(self.amount.get())
        age = annuity_quote._check_age(self.age.get())
        gender = annuity_quote._normalize_gender(self.gender.get())
        state = annuity_quote._normalize_state(self.state.get())

        ja = _optional(self.joint_age.get())
        jg = _optional(self.joint_gender.get())
        joint_age = annuity_quote._check_age(ja) if ja is not None else None
        joint_gender = annuity_quote._normalize_gender(jg) if jg is not None else None
        if (joint_age is None) != (joint_gender is None):
            raise ValueError("Joint age and joint gender must be given together.")

        sims = int(self.sims.get())
        if sims < 2:
            raise ValueError("Sims must be at least 2.")
        years = int(self.years.get())
        if years < 1:
            raise ValueError("Years must be at least 1.")
        block_length = int(self.block_length.get())

        inflation = _float_or_zero(self.inflation)
        if inflation <= -1:
            raise ValueError("Inflation must be greater than -1 (i.e. > -100%).")

        quotes = self.quotes.get()
        # One field serves as both the fixed discount rate (static) and the
        # dynamic starting rate; a blank reads as 0.
        interest = _float_or_zero(self.interest)
        if interest <= -1:
            raise ValueError("Interest rate must be greater than -1 (i.e. > -100%).")
        improvement = bool(self.improvement.get())
        dynamic = bool(self.dynamic.get())
        if dynamic and quotes != "local":
            raise ValueError("Dynamic rates require the local quotes source.")
        if dynamic and self.model.get() != "us":
            raise ValueError("Dynamic inflation + rate is only available with "
                             "the US sample (Model = us).")

        def factor(widget):
            v = _optional(widget.get())
            return float(v) if v is not None else None

        upper = factor(self.upper_bound)
        lower = factor(self.lower_bound)
        if upper is not None and upper <= 0:
            raise ValueError("Upper bound must be positive.")
        if lower is not None and lower < 0:
            raise ValueError("Lower bound must not be negative.")
        if upper is not None and lower is not None and lower > upper:
            raise ValueError("Lower bound must not exceed upper bound.")

        seed_text = _optional(self.seed.get())
        seed = int(seed_text) if seed_text is not None else None

        return dict(
            amount=amount, age=age, gender=gender, state=state,
            joint_age=joint_age, joint_gender=joint_gender,
            sims=sims, years=years, model=self.model.get(),
            block_length=block_length, seed=seed,
            inflation=inflation, upper_bound=upper, lower_bound=lower,
            quotes=quotes, interest=interest, improvement=improvement,
            dynamic_rates=dynamic, initial_rate=interest,
        )

    # ----- actions -----------------------------------------------------------
    def on_submit(self):
        try:
            params = self._collect_params()
        except (argparse.ArgumentTypeError, ValueError) as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.submit.configure(state="disabled")
        self.export_pdf.configure(state="disabled")
        self.export_csv.configure(state="disabled")
        self.status.configure(text="Running... (fetching annuity rates)")
        self._set_output("Running simulation, please wait...")

        threading.Thread(target=self._worker, args=(params,), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, params):
        try:
            result = mc.build_report(**params)
            self._queue.put(("ok", result))
        except Exception as exc:  # surfaced to the user in _poll
            self._queue.put(("err", exc))

    def _poll(self):
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return

        self.submit.configure(state="normal")
        if kind == "err":
            self.status.configure(text="Error.")
            self._set_output("")
            messagebox.showerror("Simulation failed", str(payload))
            return

        report_text, csv_kwargs, report_data = payload
        self._last_csv_kwargs = csv_kwargs
        self._last_report_data = report_data
        self._set_output(report_text)
        self.export_pdf.configure(state="normal")
        self.export_csv.configure(state="normal")
        self.status.configure(text="Done.")

    def _announce_saved(self, path):
        """Report the save and open the file in its OS default application."""
        try:
            _open_file(pathlib.Path(path))
        except OSError as exc:
            self.status.configure(text=f"Wrote {path} (could not open: {exc})")
            return
        self.status.configure(text=f"Wrote {path} (opened)")

    def on_open_doc(self, filename):
        path = _HERE / filename
        if not path.exists():
            messagebox.showerror("Not found", f"{filename} is not in {_HERE}.")
            return
        try:
            _open_file(path)
        except OSError as exc:
            messagebox.showerror("Could not open", str(exc))
            return
        self.status.configure(text=f"Opened {filename}")

    def on_export_pdf(self):
        if self._last_report_data is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export PDF report", defaultextension=".pdf",
            initialfile="montecarlo_report.pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        self.status.configure(text="Rendering PDF report...")
        self.root.update_idletasks()
        try:
            import report_pdf
        except ImportError as exc:
            messagebox.showerror(
                "Missing dependency",
                f"The graphical PDF report needs matplotlib, which is not "
                f"installed in this environment ({exc}).\n\n"
                f"Install it with:\n    pip install -r requirements.txt")
            self.status.configure(text="Error: matplotlib not installed.")
            return
        try:
            report_pdf.write_report_pdf(path, self._last_report_data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export failed", str(exc))
            self.status.configure(text="Error.")
            return
        self._announce_saved(path)

    def on_export_csv(self):
        if self._last_csv_kwargs is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export CSV", defaultextension=".csv",
            initialfile="montecarlo_report.csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            mc.write_csv(path, **self._last_csv_kwargs)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self._announce_saved(path)


def main():
    root = tk.Tk()
    MonteCarloGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
