"""
Graphical user interface for the Meowcoin Market Maker bot.

Built with tkinter (included with Python — no extra dependencies).
Provides a dashboard with Start/Stop controls, live log output,
status monitoring, and a settings editor.
"""

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, Optional

import yaml

from market_maker.config import load_config, get_app_dir, BotConfig
from market_maker.exchange_client import NonKYCClient
from market_maker.risk_manager import RiskManager
from market_maker.strategy import MarketMaker

DISCLAIMER = (
    "LEGAL DISCLAIMER\n\n"
    "This software is provided for EDUCATIONAL and INFORMATIONAL "
    "purposes only.\n\n"
    "1. You are solely responsible for compliance with all applicable "
    "laws and regulations in your jurisdiction.\n\n"
    "2. Cryptocurrency trading carries significant risk of financial "
    "loss. Past performance does not guarantee future results.\n\n"
    "3. Market making on unregulated or lightly regulated exchanges "
    "may carry legal risk. Consult a qualified legal professional.\n\n"
    "4. This bot does NOT engage in wash trading, spoofing, layering, "
    "or any form of market manipulation.\n\n"
    "5. The developers assume no liability for financial losses or "
    "legal consequences from using this software.\n\n"
    "6. You confirm you have read LEGAL_NOTICE.md in full.\n\n"
    "Do you accept these terms?"
)


# ---------------------------------------------------------------------------
# Logging handler that feeds the GUI log panel
# ---------------------------------------------------------------------------


class QueueLogHandler(logging.Handler):
    """Puts formatted log records into a thread-safe queue."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------


class MarketMakerGUI:
    """Tkinter-based GUI for the Meowcoin Market Maker."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Meowcoin Market Maker")
        self.root.geometry("860x720")
        self.root.minsize(760, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── State ──
        self.log_queue: queue.Queue = queue.Queue()
        self.bot_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.bot: Optional[MarketMaker] = None
        self.risk: Optional[RiskManager] = None
        self.config: Optional[BotConfig] = None
        self.setting_vars: Dict[str, tk.StringVar] = {}

        # ── Load existing config ──
        self._load_config()

        # ── Build UI ──
        self._build_ui()
        self._populate_fields()

        # ── Attach log handler ──
        self._setup_logging()

        # ── Periodic polling ──
        self._poll_log_queue()
        self._poll_status()

        # ── Show disclaimer on first launch ──
        self.root.after(200, self._show_disclaimer)

    # -----------------------------------------------------------------
    # Config helpers
    # -----------------------------------------------------------------

    def _load_config(self) -> None:
        try:
            self.config = load_config()
        except Exception:
            self.config = BotConfig()

    # -----------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------

    def _build_ui(self) -> None:
        style = ttk.Style()
        for theme in ("clam", "vista", "xpnative", "winnative"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        style.configure("Green.TButton", foreground="green")
        style.configure("Red.TButton", foreground="red")

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(
            main,
            text="Meowcoin Market Maker  —  MEWC / USDT",
            font=("Helvetica", 15, "bold"),
        ).pack(pady=(0, 8))

        # Notebook
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._build_dashboard_tab()
        self._build_settings_tab()

    # ── Dashboard tab ──

    def _build_dashboard_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Dashboard  ")

        # — API Credentials —
        cred = ttk.LabelFrame(tab, text="API Credentials", padding=8)
        cred.pack(fill=tk.X, pady=(0, 6))

        self.api_key_var = tk.StringVar()
        self.api_secret_var = tk.StringVar()

        ttk.Label(cred, text="API Key:").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        ttk.Entry(cred, textvariable=self.api_key_var, width=52).grid(
            row=0, column=1, sticky=tk.EW
        )

        ttk.Label(cred, text="API Secret:").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=(4, 0)
        )
        ttk.Entry(cred, textvariable=self.api_secret_var, width=52, show="*").grid(
            row=1, column=1, sticky=tk.EW, pady=(4, 0)
        )
        cred.columnconfigure(1, weight=1)

        # — Controls —
        ctrl = ttk.Frame(tab)
        ctrl.pack(fill=tk.X, pady=6)

        self.start_btn = ttk.Button(
            ctrl, text="  Start Bot  ", command=self._start_bot, style="Green.TButton"
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_btn = ttk.Button(
            ctrl,
            text="  Stop Bot  ",
            command=self._stop_bot,
            style="Red.TButton",
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(ctrl, text="Save Credentials", command=self._save_credentials).pack(
            side=tk.LEFT
        )

        ttk.Button(
            ctrl, text="Test Connection", command=self._test_connection
        ).pack(side=tk.LEFT, padx=(6, 0))

        # — Status —
        status = ttk.LabelFrame(tab, text="Status", padding=8)
        status.pack(fill=tk.X, pady=(0, 6))

        self.status_var = tk.StringVar(value="Stopped")
        self.mid_price_var = tk.StringVar(value="Mid Price: --")
        self.cycles_var = tk.StringVar(value="Cycles: 0")
        self.balance_var = tk.StringVar(value="MEWC: --  |  USDT: --")

        row = ttk.Frame(status)
        row.pack(fill=tk.X)
        ttk.Label(row, textvariable=self.status_var, font=("Helvetica", 11, "bold")).pack(
            side=tk.LEFT, padx=(0, 20)
        )
        ttk.Label(row, textvariable=self.mid_price_var).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(row, textvariable=self.cycles_var).pack(side=tk.LEFT)
        ttk.Label(status, textvariable=self.balance_var).pack(anchor=tk.W, pady=(4, 0))

        # — Log —
        log_frame = ttk.LabelFrame(tab, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=14,
            font=("Consolas", 9),
            state=tk.DISABLED,
            background="#1e1e1e",
            foreground="#d4d4d4",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Tag for coloured log levels
        self.log_text.tag_configure("ERROR", foreground="#f44747")
        self.log_text.tag_configure("WARNING", foreground="#cca700")
        self.log_text.tag_configure("INFO", foreground="#d4d4d4")

    # ── Settings tab ──

    def _build_settings_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Settings  ")

        # Scrollable content
        canvas = tk.Canvas(tab, highlightthickness=0)
        vsb = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # — Strategy —
        sf = ttk.LabelFrame(inner, text="Strategy", padding=10)
        sf.pack(fill=tk.X, pady=(0, 10), padx=4)

        strat_fields = [
            ("spread_pct", "Spread (e.g. 2 = 2%)"),
            ("num_levels", "Order Levels (per side)"),
            ("level_step_pct", "Level Step (e.g. 0.5 = 0.5%)"),
            ("base_quantity", "Base Quantity (MEWC)"),
            ("quantity_multiplier", "Quantity Multiplier"),
            ("min_spread_pct", "Min Spread (e.g. 1 = 1%)"),
            ("min_bid_price", "Min Bid Price ($, 0=off)"),
            ("min_order_value_usdt", "Min Order Value (USDT)"),
            ("refresh_interval_sec", "Refresh Interval (sec)"),
        ]
        for i, (key, label) in enumerate(strat_fields):
            var = tk.StringVar()
            self.setting_vars[f"strategy.{key}"] = var
            ttk.Label(sf, text=f"{label}:").grid(
                row=i, column=0, sticky=tk.W, pady=3, padx=(0, 10)
            )
            ttk.Entry(sf, textvariable=var, width=14).grid(
                row=i, column=1, sticky=tk.W, pady=3
            )

        # — Risk —
        rf = ttk.LabelFrame(inner, text="Risk Management", padding=10)
        rf.pack(fill=tk.X, pady=(0, 10), padx=4)

        risk_fields = [
            ("max_mewc_exposure", "Max MEWC Exposure"),
            ("max_usdt_exposure", "Max USDT Exposure"),
            ("inventory_skew_factor", "Inventory Skew Factor"),
            ("max_balance_usage_pct", "Max Balance Usage (e.g. 80 = 80%)"),
            ("stop_loss_usdt", "Stop Loss (USDT)"),
            ("max_open_orders", "Max Open Orders"),
            ("daily_loss_limit_usdt", "Daily Loss Limit (USDT)"),
        ]
        for i, (key, label) in enumerate(risk_fields):
            var = tk.StringVar()
            self.setting_vars[f"risk.{key}"] = var
            ttk.Label(rf, text=f"{label}:").grid(
                row=i, column=0, sticky=tk.W, pady=3, padx=(0, 10)
            )
            ttk.Entry(rf, textvariable=var, width=14).grid(
                row=i, column=1, sticky=tk.W, pady=3
            )

        # Buttons row
        btn_row = ttk.Frame(inner)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="Save Settings", command=self._save_settings).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Button(btn_row, text="Reset to Defaults", command=self._reset_defaults).pack(
            side=tk.LEFT
        )

    # -----------------------------------------------------------------
    # Populate fields from loaded config
    # -----------------------------------------------------------------

    def _populate_fields(self) -> None:
        if not self.config:
            return

        # Fields whose internal representation is a fraction (0.02) but
        # should be displayed/entered as a percentage (2).
        self._pct_fields = {
            "strategy.spread_pct",
            "strategy.level_step_pct",
            "strategy.min_spread_pct",
            "risk.max_balance_usage_pct",
        }

        self.api_key_var.set(self.config.exchange.api_key or "")
        self.api_secret_var.set(self.config.exchange.api_secret or "")

        s = self.config.strategy
        r = self.config.risk
        values: Dict[str, str] = {
            "strategy.spread_pct": str(s.spread_pct),
            "strategy.num_levels": str(s.num_levels),
            "strategy.level_step_pct": str(s.level_step_pct),
            "strategy.base_quantity": str(s.base_quantity),
            "strategy.quantity_multiplier": str(s.quantity_multiplier),
            "strategy.min_spread_pct": str(s.min_spread_pct),
            "strategy.min_bid_price": str(s.min_bid_price),
            "strategy.min_order_value_usdt": str(s.min_order_value_usdt),
            "strategy.refresh_interval_sec": str(s.refresh_interval_sec),
            "risk.max_mewc_exposure": str(r.max_mewc_exposure),
            "risk.max_usdt_exposure": str(r.max_usdt_exposure),
            "risk.inventory_skew_factor": str(r.inventory_skew_factor),
            "risk.max_balance_usage_pct": str(r.max_balance_usage_pct),
            "risk.stop_loss_usdt": str(r.stop_loss_usdt),
            "risk.max_open_orders": str(r.max_open_orders),
            "risk.daily_loss_limit_usdt": str(r.daily_loss_limit_usdt),
        }
        for key, val in values.items():
            if key in self.setting_vars:
                # Convert fraction → percentage for display
                if key in self._pct_fields:
                    display_val = str(round(float(val) * 100, 4))
                else:
                    display_val = val
                self.setting_vars[key].set(display_val)

    # -----------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------

    def _setup_logging(self) -> None:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"
        )
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(fmt)
        for name in ("mewc_mm", "mewc_mm.exchange", "mewc_mm.strategy", "mewc_mm.risk"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            lg.addHandler(handler)

    def _poll_log_queue(self) -> None:
        """Drain the queue and append to the log text widget (runs on main thread)."""
        batch = 0
        while batch < 200:  # cap per tick
            try:
                msg: str = self.log_queue.get_nowait()
            except queue.Empty:
                break
            batch += 1

            tag = "INFO"
            if "| ERROR" in msg or "| CRITICAL" in msg:
                tag = "ERROR"
            elif "| WARNING" in msg:
                tag = "WARNING"

            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(100, self._poll_log_queue)

    # -----------------------------------------------------------------
    # Status polling
    # -----------------------------------------------------------------

    def _poll_status(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            label = "Running"
            if self.risk and self.risk.is_halted:
                label = f"HALTED — {self.risk.halt_reason}"
            self.status_var.set(label)
            if self.bot:
                self.cycles_var.set(f"Cycles: {self.bot._cycle_count}")
            if self.risk:
                p = self.risk.position
                if p.last_mid_price > 0:
                    self.mid_price_var.set(f"Mid: ${p.last_mid_price:.6f}")
                    self.balance_var.set(
                        f"MEWC: {p.mewc_balance:.2f}  |  USDT: {p.usdt_balance:.4f}"
                    )
        elif self.bot_thread and not self.bot_thread.is_alive():
            self.status_var.set("Stopped")
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
            self.bot_thread = None

        self.root.after(1000, self._poll_status)

    # -----------------------------------------------------------------
    # Bot control
    # -----------------------------------------------------------------

    def _start_bot(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            return

        # Persist current credential values
        self._save_credentials(silent=True)

        # Reload config so new creds / settings are picked up
        self._load_config()

        if not self.config.exchange.api_key or not self.config.exchange.api_secret:
            messagebox.showwarning(
                "Missing Credentials",
                "Please enter your NonKYC API Key and Secret before starting.",
            )
            return

        self.stop_event.clear()
        self.status_var.set("Starting...")
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)

        try:
            # Ensure log directory exists
            app_dir = get_app_dir()
            log_file = self.config.logging.file
            if not os.path.isabs(log_file):
                log_file = str(app_dir / log_file)
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            client = NonKYCClient(self.config.exchange)
            self.risk = RiskManager(self.config.risk)
            self.bot = MarketMaker(self.config, client, self.risk)
        except Exception as e:
            messagebox.showerror("Initialisation Error", str(e))
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
            self.status_var.set("Stopped")
            return

        self.bot_thread = threading.Thread(
            target=self._run_bot, daemon=True, name="BotThread"
        )
        self.bot_thread.start()

    def _run_bot(self) -> None:
        """Target for the background thread."""
        try:
            self.bot.run(stop_event=self.stop_event)
        except Exception as e:
            logging.getLogger("mewc_mm").error("Bot stopped with error: %s", e)

    def _stop_bot(self) -> None:
        if not self.bot_thread or not self.bot_thread.is_alive():
            return
        self.status_var.set("Stopping...")
        self.stop_event.set()
        if self.bot:
            self.bot.stop()

    # -----------------------------------------------------------------
    # Save helpers
    # -----------------------------------------------------------------

    def _save_credentials(self, silent: bool = False) -> None:
        env_path = get_app_dir() / ".env"
        try:
            with open(env_path, "w") as f:
                f.write(f"NONKYC_API_KEY={self.api_key_var.get().strip()}\n")
                f.write(f"NONKYC_API_SECRET={self.api_secret_var.get().strip()}\n")
            if not silent:
                messagebox.showinfo("Saved", f"Credentials saved to:\n{env_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save credentials:\n{e}")

    def _test_connection(self) -> None:
        """Test API connectivity and authentication in a background thread."""
        # Save current credentials first
        self._save_credentials(silent=True)

        # Reload config so the latest creds are picked up
        self._load_config()

        if not self.config.exchange.api_key or not self.config.exchange.api_secret:
            messagebox.showwarning(
                "Missing Credentials",
                "Please enter your NonKYC API Key and Secret first.",
            )
            return

        def _run_test():
            try:
                client = NonKYCClient(self.config.exchange)
                result = client.test_connection()
                # Schedule the result dialog on the main thread
                self.root.after(0, lambda: self._show_test_result(result))
            except Exception as exc:
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "Connection Test Failed",
                        f"Unexpected error:\n{exc}",
                    ),
                )

        threading.Thread(target=_run_test, daemon=True).start()

    def _show_test_result(self, result: dict) -> None:
        """Display the test_connection result to the user."""
        if result["ok"]:
            delta = result["server_time_delta_ms"]
            messagebox.showinfo(
                "Connection Test Passed",
                "Public API: OK\n"
                "Authentication: OK\n"
                f"Clock skew: {delta:+d} ms\n\n"
                "Your API credentials are working correctly!",
            )
        else:
            parts = []
            parts.append(f"Public API: {'OK' if result['public'] else 'FAILED'}")
            parts.append(
                f"Authentication: {'OK' if result['authenticated'] else 'FAILED'}"
            )
            if result["server_time_delta_ms"]:
                parts.append(
                    f"Clock skew: {result['server_time_delta_ms']:+d} ms"
                )
            parts.append(f"\nError:\n{result['error']}")
            messagebox.showerror("Connection Test Failed", "\n".join(parts))

    def _save_settings(self) -> None:
        int_fields = {"num_levels", "refresh_interval_sec", "max_open_orders"}
        try:
            config_data = {
                "exchange": {
                    "base_url": "https://api.nonkyc.io/api/v2",
                    "ws_url": "wss://ws.nonkyc.io",
                    "symbol": "MEWC/USDT",
                },
                "strategy": {},
                "risk": {},
                "logging": {
                    "level": "INFO",
                    "file": "logs/market_maker.log",
                    "console": True,
                    "max_file_size_mb": 10,
                    "backup_count": 5,
                },
            }
            for key, var in self.setting_vars.items():
                section, field = key.split(".", 1)
                raw = var.get().strip()
                if field in int_fields:
                    config_data[section][field] = int(raw)
                else:
                    val = float(raw)
                    # Convert percentage → fraction for storage
                    if key in self._pct_fields:
                        val = val / 100.0
                    config_data[section][field] = val

            cfg_path = get_app_dir() / "config.yaml"
            with open(cfg_path, "w") as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

            messagebox.showinfo(
                "Saved",
                f"Settings saved to:\n{cfg_path}\n\n"
                "Restart the bot for changes to take effect.",
            )
        except ValueError as e:
            messagebox.showerror(
                "Invalid Value",
                f"One or more fields contain invalid numbers.\n\n{e}",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not save settings:\n{e}")

    def _reset_defaults(self) -> None:
        """Overwrite config.yaml with bundled defaults and refresh fields."""
        if not messagebox.askyesno(
            "Reset Settings",
            "This will replace your config.yaml with the built-in defaults.\n\n"
            "Your API credentials (.env) will NOT be affected.\n\nContinue?",
        ):
            return
        from market_maker.config import _ensure_user_file
        _ensure_user_file("config.yaml", force=True)
        self._load_config()
        self._populate_fields()
        messagebox.showinfo("Reset", "Settings restored to defaults.")

    # -----------------------------------------------------------------
    # Disclaimer
    # -----------------------------------------------------------------

    def _show_disclaimer(self) -> None:
        if not messagebox.askyesno("Legal Disclaimer", DISCLAIMER, icon="warning"):
            self.root.destroy()
            sys.exit(0)

    # -----------------------------------------------------------------
    # Window close
    # -----------------------------------------------------------------

    def _on_close(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            if not messagebox.askyesno(
                "Confirm Exit", "The bot is still running.\nStop it and exit?"
            ):
                return
            self._stop_bot()
            self.bot_thread.join(timeout=5)
        self.root.destroy()

    # -----------------------------------------------------------------
    # Entry
    # -----------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main-loop."""
        self.root.mainloop()
