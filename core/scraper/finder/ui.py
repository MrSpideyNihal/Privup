# /*
#  *  ╔════════════════════════════════════════════════════════════╗
#  *  ║                                                            ║
#  *  ║                     PRIVACY-URL-FINDER                     ║
#  *  ║                                                            ║
#  *  ║                         by Nihal Rodge                     ║
#  *  ║                                                            ║
#  *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
#  *  ║                                                            ║
#  *  ╚════════════════════════════════════════════════════════════╝
#  */
#
# This code was integrated from privacy-url-finder:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Native Desktop GUI for Privacy URL Finder (Zero Web, Zero Server)."""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from .dataset.manager import DatasetManager
from .finder import PrivacyURLFinder
from .models import ResolutionStatus, SourceType

# Theme colors (Dark Slate / Cyberpunk Minimal)
COLOR_BG = "#0b0f19"          # Deep dark background
COLOR_SURFACE = "#151d30"     # Card/container surface
COLOR_SURFACE_ALT = "#1c2742" # Nested card
COLOR_BORDER = "#2a3b5c"      # Subtle border
COLOR_PRIMARY = "#3b82f6"     # Accent blue
COLOR_PRIMARY_HOVER = "#2563eb"
COLOR_TEXT = "#f8fafc"        # Bright text
COLOR_MUTED = "#94a3b8"       # Secondary text
COLOR_FAINT = "#64748b"       # Faint labels
COLOR_SUCCESS = "#10b981"     # Emerald
COLOR_WARNING = "#f59e0b"     # Amber
COLOR_DANGER = "#ef4444"      # Rose


class PrivacyFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PrivUp - Privacy URL Finder")
        self.root.geometry("820x680")
        self.root.minsize(740, 600)
        self.root.configure(bg=COLOR_BG)

        self.finder = PrivacyURLFinder()
        self.dataset_mgr = DatasetManager()
        self.current_result = None

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Configure dark theme for ttk widgets
        self.style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 10))
        self.style.configure("TFrame", background=COLOR_BG)
        self.style.configure("Card.TFrame", background=COLOR_SURFACE, relief="flat")
        self.style.configure("CardAlt.TFrame", background=COLOR_SURFACE_ALT, relief="flat")

        self.style.configure(
            "Primary.TButton",
            background=COLOR_PRIMARY,
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            focusthickness=0,
            padding=(18, 8),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", COLOR_PRIMARY_HOVER), ("disabled", "#475569")],
            foreground=[("disabled", "#94a3b8")],
        )

        self.style.configure(
            "Action.TButton",
            background=COLOR_SURFACE_ALT,
            foreground=COLOR_TEXT,
            font=("Segoe UI", 9),
            borderwidth=1,
            focusthickness=0,
            padding=(10, 4),
        )
        self.style.map(
            "Action.TButton",
            background=[("active", "#2d3d66")],
        )

        self.style.configure(
            "Pill.TButton",
            background=COLOR_SURFACE_ALT,
            foreground="#93c5fd",
            font=("Segoe UI", 9),
            borderwidth=0,
            padding=(8, 3),
        )
        self.style.map("Pill.TButton", background=[("active", "#253456")])

        self.style.configure(
            "LendingPill.TButton",
            background="#272115",
            foreground="#fcd34d",
            font=("Segoe UI", 9),
            borderwidth=0,
            padding=(8, 3),
        )
        self.style.map("LendingPill.TButton", background=[("active", "#3d321d")])

        # Progress bar
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor=COLOR_SURFACE,
            background=COLOR_PRIMARY,
            borderwidth=0,
            thickness=4,
        )

    def _build_ui(self):
        # Main scrollable canvas or packed frame
        main_frame = tk.Frame(self.root, bg=COLOR_BG, padx=28, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Header
        header_frame = tk.Frame(main_frame, bg=COLOR_BG)
        header_frame.pack(fill=tk.X, pady=(0, 16))

        tag_badge = tk.Label(
            header_frame,
            text="PRIVUP DISCOVERY ENGINE",
            bg="#172554",
            fg="#60a5fa",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
        )
        tag_badge.pack(anchor="w", pady=(0, 6))

        title_lbl = tk.Label(
            header_frame,
            text="Privacy URL Finder",
            bg=COLOR_BG,
            fg="#ffffff",
            font=("Segoe UI", 20, "bold"),
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            header_frame,
            text="Locates & verifies official privacy policies on-device for digital lending apps, fintech, and websites.",
            bg=COLOR_BG,
            fg=COLOR_MUTED,
            font=("Segoe UI", 10),
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # 2. Search Box Card
        search_card = tk.Frame(main_frame, bg=COLOR_SURFACE, padx=16, pady=14, relief="flat", highlightbackground=COLOR_BORDER, highlightthickness=1)
        search_card.pack(fill=tk.X, pady=(0, 16))

        input_row = tk.Frame(search_card, bg=COLOR_SURFACE)
        input_row.pack(fill=tk.X)

        self.query_var = tk.StringVar()
        self.entry = tk.Entry(
            input_row,
            textvariable=self.query_var,
            bg=COLOR_SURFACE_ALT,
            fg="#ffffff",
            insertbackground="#ffffff",
            font=("Segoe UI", 11),
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 10))
        self.entry.bind("<Return>", lambda e: self.start_search())
        self.entry.focus_set()

        self.search_btn = ttk.Button(
            input_row,
            text="Find Policy",
            style="Primary.TButton",
            command=self.start_search,
            cursor="hand2",
        )
        self.search_btn.pack(side=tk.RIGHT)

        # Quick Suggestion Chips
        chips_frame = tk.Frame(search_card, bg=COLOR_SURFACE)
        chips_frame.pack(fill=tk.X, pady=(10, 0))

        chips_label = tk.Label(chips_frame, text="Quick test:", bg=COLOR_SURFACE, fg=COLOR_FAINT, font=("Segoe UI", 9))
        chips_label.pack(side=tk.LEFT, padx=(0, 6))

        pills = [
            ("⚡ KreditBee (NBFC)", "KreditBee", True),
            ("⚡ Navi Finserv", "Navi", True),
            ("⚡ CASHe", "CASHe", True),
            ("⚡ Ring / Kissht", "com.kissht", True),
            ("CRED", "CRED", False),
            ("Spotify", "Spotify", False),
            ("github.com", "https://github.com", False),
        ]

        for text, q, is_lending in pills:
            btn = ttk.Button(
                chips_frame,
                text=text,
                style="LendingPill.TButton" if is_lending else "Pill.TButton",
                command=lambda val=q: self.set_query(val),
                cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=3)

        # Progress Bar (Hidden initially)
        self.progress_bar = ttk.Progressbar(main_frame, mode="indeterminate", style="Horizontal.TProgressbar")

        # 3. Results Container Frame
        self.results_frame = tk.Frame(
            main_frame,
            bg=COLOR_SURFACE,
            padx=20,
            pady=18,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        # Initially not packed until search runs

        # Results internal widgets
        res_header = tk.Frame(self.results_frame, bg=COLOR_SURFACE)
        res_header.pack(fill=tk.X, pady=(0, 12))

        self.res_title = tk.Label(
            res_header,
            text="Entity Name",
            bg=COLOR_SURFACE,
            fg="#ffffff",
            font=("Segoe UI", 15, "bold"),
        )
        self.res_title.pack(side=tk.LEFT)

        self.status_badge = tk.Label(
            res_header,
            text="FOUND",
            bg="#064e3b",
            fg=COLOR_SUCCESS,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=3,
        )
        self.status_badge.pack(side=tk.RIGHT)

        self.res_method = tk.Label(
            self.results_frame,
            text="Resolved via Curated Dataset • 140ms",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=("Segoe UI", 9),
        )
        self.res_method.pack(anchor="w", pady=(0, 10))

        # NBFC Banner
        self.nbfc_frame = tk.Frame(
            self.results_frame,
            bg="#291b07",
            padx=12,
            pady=8,
            highlightbackground="#b45309",
            highlightthickness=1,
        )
        self.nbfc_lbl = tk.Label(
            self.nbfc_frame,
            text="🏛️ Regulated NBFC Partner: Krazybee Services Private Limited",
            bg="#291b07",
            fg="#fef3c7",
            font=("Segoe UI", 9, "bold"),
        )
        self.nbfc_lbl.pack(anchor="w")

        # URL Frame Box
        url_box = tk.Frame(self.results_frame, bg=COLOR_SURFACE_ALT, padx=12, pady=10)
        url_box.pack(fill=tk.X, pady=(10, 14))

        self.url_entry = tk.Entry(
            url_box,
            bg=COLOR_SURFACE_ALT,
            fg="#60a5fa",
            font=("Consolas", 10),
            relief="flat",
            readonlybackground=COLOR_SURFACE_ALT,
            state="readonly",
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        copy_btn = ttk.Button(url_box, text="📋 Copy", style="Action.TButton", command=self.copy_url, cursor="hand2")
        copy_btn.pack(side=tk.RIGHT, padx=(0, 4))

        open_btn = ttk.Button(url_box, text="🌐 Open", style="Action.TButton", command=self.open_url, cursor="hand2")
        open_btn.pack(side=tk.RIGHT)

        # Stats Grid Frame
        stats_frame = tk.Frame(self.results_frame, bg=COLOR_SURFACE)
        stats_frame.pack(fill=tk.X, pady=(0, 14))

        self.stat_conf = self._create_stat_card(stats_frame, "CONFIDENCE", "90%", 0)
        self.stat_source = self._create_stat_card(stats_frame, "SOURCE", "DATASET", 1)
        self.stat_domain = self._create_stat_card(stats_frame, "DOMAIN", "-", 2)
        self.stat_time = self._create_stat_card(stats_frame, "TIME", "0 ms", 3)

        # Signals Accordion List
        signals_container = tk.Frame(self.results_frame, bg=COLOR_SURFACE)
        signals_container.pack(fill=tk.BOTH, expand=True)

        sig_lbl = tk.Label(
            signals_container,
            text="Policy Content Signals & Verification:",
            bg=COLOR_SURFACE,
            fg=COLOR_FAINT,
            font=("Segoe UI", 9, "bold"),
        )
        sig_lbl.pack(anchor="w", pady=(0, 6))

        self.signals_text = tk.Text(
            signals_container,
            height=4,
            bg=COLOR_SURFACE_ALT,
            fg=COLOR_TEXT,
            font=("Segoe UI", 9),
            relief="flat",
            padx=8,
            pady=6,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
        )
        self.signals_text.pack(fill=tk.X)
        self.signals_text.config(state="disabled")

        # 4. Footer info
        footer_frame = tk.Frame(main_frame, bg=COLOR_BG)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

        catalog_len = len(self.dataset_mgr.entries)
        status_info = tk.Label(
            footer_frame,
            text=f"Curated database: {catalog_len}+ verified services & NBFC lenders  •  Zero network leakage  •  PrivUp Engine",
            bg=COLOR_BG,
            fg=COLOR_FAINT,
            font=("Segoe UI", 8),
        )
        status_info.pack(anchor="w")

    def _create_stat_card(self, parent, label_text, default_val, col_idx):
        card = tk.Frame(parent, bg=COLOR_SURFACE_ALT, padx=10, pady=6, highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)

        lbl = tk.Label(card, text=label_text, bg=COLOR_SURFACE_ALT, fg=COLOR_FAINT, font=("Segoe UI", 7, "bold"))
        lbl.pack(anchor="w")

        val_lbl = tk.Label(card, text=default_val, bg=COLOR_SURFACE_ALT, fg="#ffffff", font=("Segoe UI", 10, "bold"))
        val_lbl.pack(anchor="w")
        return val_lbl

    def set_query(self, query: str):
        self.query_var.set(query)
        self.start_search()

    def start_search(self):
        query = self.query_var.get().strip()
        if not query:
            return

        self.search_btn.config(state="disabled")
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_bar.start(10)

        # Run search asynchronously in a background thread to prevent GUI freezing
        threading.Thread(target=self._run_search_thread, args=(query,), daemon=True).start()

    def _run_search_thread(self, query: str):
        try:
            result = self.finder.find(query)
            # Safe update on main thread
            self.root.after(0, self._render_result, result)
        except Exception as e:
            self.root.after(0, self._handle_search_error, str(e))

    def _handle_search_error(self, err_msg: str):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.search_btn.config(state="normal")
        messagebox.showerror("Resolution Error", f"Failed to resolve query:\n{err_msg}")

    def _render_result(self, result):
        self.current_result = result
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.search_btn.config(state="normal")

        # Show results frame
        self.results_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # Title & Method
        self.res_title.config(text=result.entity_name or result.title or result.query)
        self.res_method.config(text=f"Resolved via {result.method}  •  Source: {result.source.value if result.source else 'None'}")

        # Status badge
        if result.status == ResolutionStatus.FOUND:
            self.status_badge.config(text="✓ FOUND", bg="#064e3b", fg=COLOR_SUCCESS)
        elif result.status == ResolutionStatus.PROBABLE:
            self.status_badge.config(text="? PROBABLE", bg="#451a03", fg=COLOR_WARNING)
        else:
            self.status_badge.config(text="✗ NOT FOUND", bg="#4c0519", fg=COLOR_DANGER)

        # Regulated NBFC Partner
        if result.metadata and result.metadata.get("regulated_nbfc"):
            nbfc = result.metadata["regulated_nbfc"]
            self.nbfc_lbl.config(text=f"🏛️ Regulated NBFC Partner: {nbfc}")
            self.nbfc_frame.pack(fill=tk.X, pady=(0, 10))
        else:
            self.nbfc_frame.pack_forget()

        # URL
        self.url_entry.config(state="normal")
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, result.url or "No privacy policy URL found.")
        self.url_entry.config(state="readonly")

        # Stats
        self.stat_conf.config(text=f"{int(result.confidence * 100)}%")
        self.stat_source.config(text=result.source.value if result.source else "None")
        self.stat_domain.config(text=result.domain or "-")
        self.stat_time.config(text=f"{result.elapsed_ms:.0f} ms")

        # Signals
        self.signals_text.config(state="normal")
        self.signals_text.delete("1.0", tk.END)
        if result.validation and result.validation.signals:
            for sig in result.validation.signals:
                self.signals_text.insert(tk.END, f"  • {sig}\n")
        elif result.status == ResolutionStatus.FOUND:
            self.signals_text.insert(tk.END, "  • Verified official catalog entry with matching entity record.\n")
        else:
            self.signals_text.insert(tk.END, "  • Insufficient textual policy signals detected.\n")
        self.signals_text.config(state="disabled")

    def copy_url(self):
        if self.current_result and self.current_result.url:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.current_result.url)
            self.root.update()

    def open_url(self):
        if self.current_result and self.current_result.url:
            webbrowser.open(self.current_result.url)


def launch_gui():
    """Launch the native desktop application."""
    root = tk.Tk()
    app = PrivacyFinderApp(root)
    root.mainloop()


def main():
    launch_gui()


if __name__ == "__main__":
    main()
