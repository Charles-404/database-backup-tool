import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import winreg
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import END, LEFT, W, filedialog, messagebox, StringVar
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None

try:
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    pystray = None
    Image = None
    ImageDraw = None


APP_NAME = "SQLServerBackupTool"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "logs" / "app.log"
RESOURCE_DIR = get_resource_dir()
ASSETS_DIR = RESOURCE_DIR / "assets"
ICON_ICO_FILE = ASSETS_DIR / "app_icon.ico"
ICON_PNG_FILE = ASSETS_DIR / "app_icon.png"


@dataclass
class AppConfig:
    db_type: str = "sqlserver"
    server: str = "localhost"
    port: str = "1433"
    database: str = ""
    auth_mode: str = "windows"
    username: str = ""
    password: str = ""
    backup_dir: str = str(BASE_DIR / "backups")
    backup_name: str = ""
    retention_days: str = "30"
    schedule_enabled: bool = False
    schedule_type: str = "daily"
    schedule_time: str = "02:00"
    schedule_interval_minutes: str = "60"
    minimize_to_tray: bool = True
    start_with_windows: bool = False
    tray_notifications: bool = True
    startup_minimized: bool = False


class SqlServerBackupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("数据库备份工具")
        self.root.geometry("1040x800")
        self.root.minsize(940, 740)
        self.apply_window_icon()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.is_busy = False
        self.scheduler_stop_event = threading.Event()
        self.last_schedule_key: str | None = None
        self.last_cleanup_key: str | None = None
        self.tray_icon = None
        self.tray_thread = None
        self.tray_available = pystray is not None and Image is not None and ImageDraw is not None
        self.is_hidden_to_tray = False
        self.is_exiting = False
        self.tray_hint_shown = False

        self.db_type_var = StringVar(value="sqlserver")
        self.server_var = StringVar()
        self.port_var = StringVar()
        self.database_var = StringVar()
        self.auth_mode_var = StringVar(value="windows")
        self.username_var = StringVar()
        self.password_var = StringVar()
        self.backup_dir_var = StringVar()
        self.backup_name_var = StringVar()
        self.retention_days_var = StringVar(value="30")
        self.schedule_enabled_var = tk.BooleanVar(value=False)
        self.schedule_type_var = StringVar(value="daily")
        self.schedule_time_var = StringVar(value="02:00")
        self.schedule_interval_var = StringVar(value="60")
        self.minimize_to_tray_var = tk.BooleanVar(value=True)
        self.start_with_windows_var = tk.BooleanVar(value=False)
        self.tray_notifications_var = tk.BooleanVar(value=True)
        self.startup_minimized_var = tk.BooleanVar(value=False)

        self.database_combo: ttk.Combobox | None = None
        self.username_entry: ttk.Entry | None = None
        self.password_entry: ttk.Entry | None = None
        self.schedule_time_entry: ttk.Entry | None = None
        self.schedule_interval_entry: ttk.Entry | None = None
        self.log_text: ScrolledText | None = None
        self.status_var = StringVar(value="就绪")
        self.db_type_hint_label: ttk.Label | None = None
        self.auth_frame: ttk.Frame | None = None
        self.left_canvas: tk.Canvas | None = None

        self.build_ui()
        self.load_config(auto=True)
        self.sync_startup_state(show_message=False)
        self.process_log_queue()
        self.start_scheduler()
        self.setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Unmap>", self.on_window_unmap)
        self.root.after(300, self.apply_startup_window_mode)

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="数据库备份工具",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            header,
            text="支持 SQL Server 和 MySQL 的连接测试、手动备份、定时备份、托盘运行、开机自启动和托盘通知。",
            foreground="#555555",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        body = ttk.Frame(self.root, padding=(16, 0, 16, 16))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        config_card = ttk.LabelFrame(body, text="数据库配置", padding=16)
        config_card.grid(row=0, column=0, columnspan=2, sticky="ew")
        config_card.columnconfigure(1, weight=1)
        config_card.columnconfigure(3, weight=1)

        ttk.Label(config_card, text="数据库类型").grid(row=0, column=0, sticky=W, padx=(0, 8), pady=6)
        type_frame = ttk.Frame(config_card)
        type_frame.grid(row=0, column=1, columnspan=3, sticky="w", pady=6)
        ttk.Radiobutton(
            type_frame,
            text="SQL Server",
            value="sqlserver",
            variable=self.db_type_var,
            command=self.toggle_db_type,
        ).pack(side=LEFT)
        ttk.Radiobutton(
            type_frame,
            text="MySQL",
            value="mysql",
            variable=self.db_type_var,
            command=self.toggle_db_type,
        ).pack(side=LEFT, padx=(12, 0))

        ttk.Label(config_card, text="服务器/主机").grid(row=1, column=0, sticky=W, padx=(0, 8), pady=6)
        ttk.Entry(config_card, textvariable=self.server_var).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(config_card, text="端口").grid(row=1, column=2, sticky=W, padx=(12, 8), pady=6)
        ttk.Entry(config_card, textvariable=self.port_var).grid(row=1, column=3, sticky="ew", pady=6)

        ttk.Label(config_card, text="数据库").grid(row=2, column=0, sticky=W, padx=(0, 8), pady=6)
        self.database_combo = ttk.Combobox(config_card, textvariable=self.database_var)
        self.database_combo.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Button(config_card, text="读取数据库", command=self.load_databases).grid(
            row=2, column=2, columnspan=2, sticky="ew", padx=(12, 0), pady=6
        )

        ttk.Label(config_card, text="认证方式").grid(row=3, column=0, sticky=W, padx=(0, 8), pady=6)
        self.auth_frame = ttk.Frame(config_card)
        self.auth_frame.grid(row=3, column=1, columnspan=3, sticky="w", pady=6)

        ttk.Radiobutton(
            self.auth_frame,
            text="Windows 认证",
            value="windows",
            variable=self.auth_mode_var,
            command=self.toggle_auth_mode,
        ).pack(side=LEFT)
        ttk.Radiobutton(
            self.auth_frame,
            text="SQL Server 认证",
            value="sql",
            variable=self.auth_mode_var,
            command=self.toggle_auth_mode,
        ).pack(side=LEFT, padx=(12, 0))

        ttk.Label(config_card, text="用户名").grid(row=4, column=0, sticky=W, padx=(0, 8), pady=6)
        self.username_entry = ttk.Entry(config_card, textvariable=self.username_var)
        self.username_entry.grid(row=4, column=1, sticky="ew", pady=6)

        ttk.Label(config_card, text="密码").grid(row=4, column=2, sticky=W, padx=(12, 8), pady=6)
        self.password_entry = ttk.Entry(config_card, textvariable=self.password_var, show="*")
        self.password_entry.grid(row=4, column=3, sticky="ew", pady=6)

        self.db_type_hint_label = ttk.Label(config_card, text="", foreground="#666666")
        self.db_type_hint_label.grid(row=5, column=0, columnspan=4, sticky=W, pady=(8, 0))

        left_shell = ttk.Frame(body)
        left_shell.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(16, 0))
        left_shell.columnconfigure(0, weight=1)
        left_shell.rowconfigure(0, weight=1)

        self.left_canvas = tk.Canvas(left_shell, highlightthickness=0, borderwidth=0)
        left_scrollbar = ttk.Scrollbar(left_shell, orient="vertical", command=self.left_canvas.yview)
        left_panel = ttk.Frame(self.left_canvas)
        left_window = self.left_canvas.create_window((0, 0), window=left_panel, anchor="nw")
        self.left_canvas.configure(yscrollcommand=left_scrollbar.set)
        self.left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scrollbar.grid(row=0, column=1, sticky="ns")
        left_panel.columnconfigure(0, weight=1)

        def update_left_scroll_region(_event: tk.Event) -> None:
            if self.left_canvas is not None:
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

        def update_left_panel_width(event: tk.Event) -> None:
            if self.left_canvas is not None:
                self.left_canvas.itemconfigure(left_window, width=event.width)

        def scroll_left_panel(event: tk.Event) -> str:
            if self.left_canvas is not None:
                self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        left_panel.bind("<Configure>", update_left_scroll_region)
        self.left_canvas.bind("<Configure>", update_left_panel_width)
        self.left_canvas.bind("<MouseWheel>", scroll_left_panel)

        backup_card = ttk.LabelFrame(left_panel, text="备份配置", padding=16)
        backup_card.grid(row=0, column=0, sticky="nsew")
        backup_card.columnconfigure(1, weight=1)

        ttk.Label(backup_card, text="备份目录").grid(row=0, column=0, sticky=W, padx=(0, 8), pady=6)
        ttk.Entry(backup_card, textvariable=self.backup_dir_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(backup_card, text="选择目录", command=self.choose_backup_dir).grid(
            row=0, column=2, sticky="ew", padx=(12, 0), pady=6
        )

        ttk.Label(backup_card, text="备份文件名").grid(row=1, column=0, sticky=W, padx=(0, 8), pady=6)
        ttk.Entry(backup_card, textvariable=self.backup_name_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)

        ttk.Label(backup_card, text="保留天数").grid(row=2, column=0, sticky=W, padx=(0, 8), pady=6)
        ttk.Entry(backup_card, textvariable=self.retention_days_var).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(backup_card, text="0 表示不自动清理", foreground="#666666").grid(
            row=2, column=2, sticky=W, padx=(12, 0), pady=6
        )

        ttk.Label(
            backup_card,
            text="留空时自动生成：数据库名_YYYYMMDD_HHMMSS.bak / .sql",
            foreground="#666666",
        ).grid(row=3, column=0, columnspan=3, sticky=W, pady=(4, 12))

        action_frame = ttk.Frame(backup_card)
        action_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        for column in range(4):
            action_frame.columnconfigure(column, weight=1)

        ttk.Button(action_frame, text="保存配置", command=self.save_config).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(action_frame, text="测试连接", command=self.test_connection).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(action_frame, text="开始备份", command=self.start_backup).grid(row=0, column=2, sticky="ew", padx=6)
        ttk.Button(action_frame, text="最小化到托盘", command=self.hide_to_tray).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        schedule_card = ttk.LabelFrame(left_panel, text="定时与后台", padding=16)
        schedule_card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        schedule_card.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            schedule_card,
            text="启用定时备份",
            variable=self.schedule_enabled_var,
            command=self.toggle_schedule_mode,
        ).grid(row=0, column=0, columnspan=3, sticky=W, pady=(0, 10))

        ttk.Label(schedule_card, text="计划类型").grid(row=1, column=0, sticky=W, padx=(0, 8), pady=6)
        type_frame = ttk.Frame(schedule_card)
        type_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)

        ttk.Radiobutton(
            type_frame,
            text="每天固定时间",
            value="daily",
            variable=self.schedule_type_var,
            command=self.toggle_schedule_mode,
        ).pack(side=LEFT)
        ttk.Radiobutton(
            type_frame,
            text="按间隔分钟",
            value="interval",
            variable=self.schedule_type_var,
            command=self.toggle_schedule_mode,
        ).pack(side=LEFT, padx=(12, 0))

        ttk.Label(schedule_card, text="每天时间").grid(row=2, column=0, sticky=W, padx=(0, 8), pady=6)
        self.schedule_time_entry = ttk.Entry(schedule_card, textvariable=self.schedule_time_var)
        self.schedule_time_entry.grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(schedule_card, text="格式 HH:MM", foreground="#666666").grid(row=2, column=2, sticky=W, padx=(12, 0), pady=6)

        ttk.Label(schedule_card, text="间隔分钟").grid(row=3, column=0, sticky=W, padx=(0, 8), pady=6)
        self.schedule_interval_entry = ttk.Entry(schedule_card, textvariable=self.schedule_interval_var)
        self.schedule_interval_entry.grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Label(schedule_card, text="例如 30、60、120", foreground="#666666").grid(row=3, column=2, sticky=W, padx=(12, 0), pady=6)

        ttk.Checkbutton(
            schedule_card,
            text="关闭窗口时最小化到托盘",
            variable=self.minimize_to_tray_var,
        ).grid(row=4, column=0, columnspan=3, sticky=W, pady=(10, 0))

        ttk.Checkbutton(
            schedule_card,
            text="开机自动启动程序",
            variable=self.start_with_windows_var,
        ).grid(row=5, column=0, columnspan=3, sticky=W, pady=(6, 0))

        ttk.Checkbutton(
            schedule_card,
            text="启用托盘通知",
            variable=self.tray_notifications_var,
        ).grid(row=6, column=0, columnspan=3, sticky=W, pady=(6, 0))

        ttk.Checkbutton(
            schedule_card,
            text="开机后静默最小化到托盘",
            variable=self.startup_minimized_var,
        ).grid(row=7, column=0, columnspan=3, sticky=W, pady=(6, 0))

        ttk.Label(
            schedule_card,
            text="程序保持运行时，后台会自动检查计划并执行备份。",
            foreground="#666666",
        ).grid(row=8, column=0, columnspan=3, sticky=W, pady=(8, 0))

        def bind_left_mousewheel(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", scroll_left_panel)
            for child in widget.winfo_children():
                bind_left_mousewheel(child)

        bind_left_mousewheel(left_panel)

        log_card = ttk.LabelFrame(body, text="运行日志", padding=16)
        log_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(16, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)

        self.log_text = ScrolledText(log_card, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        ttk.Button(log_card, text="清空日志", command=self.clear_logs).grid(row=1, column=0, sticky="e", pady=(12, 0))

        status_bar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        ttk.Separator(status_bar, orient="horizontal").grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(status_bar, textvariable=self.status_var).grid(row=1, column=0, sticky="w")

        self.toggle_db_type()
        self.toggle_schedule_mode()

    def choose_backup_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.backup_dir_var.get() or str(BASE_DIR))
        if selected:
            self.backup_dir_var.set(selected)

    def apply_window_icon(self) -> None:
        try:
            if ICON_ICO_FILE.exists():
                self.root.iconbitmap(default=str(ICON_ICO_FILE))
        except Exception:
            pass

    def clear_logs(self) -> None:
        if self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text("", encoding="utf-8")
        except Exception:
            pass
        self.status_var.set("日志已清空")

    def toggle_auth_mode(self) -> None:
        state = "normal" if self.db_type_var.get() == "mysql" or self.auth_mode_var.get() == "sql" else "disabled"
        if self.username_entry is not None:
            self.username_entry.configure(state=state)
        if self.password_entry is not None:
            self.password_entry.configure(state=state)

    def toggle_db_type(self) -> None:
        db_type = self.db_type_var.get()
        if db_type == "mysql":
            if self.port_var.get() in {"", "1433"}:
                self.port_var.set("3306")
            self.auth_mode_var.set("sql")
            hint = "MySQL 备份依赖 mysqldump，请确保 MySQL 客户端工具已安装并加入 PATH。"
        else:
            if self.port_var.get() in {"", "3306"}:
                self.port_var.set("1433")
            hint = "SQL Server 备份依赖 SQL Server ODBC Driver 17/18。"

        if self.auth_frame is not None:
            for child in self.auth_frame.winfo_children():
                child.configure(state="disabled" if db_type == "mysql" else "normal")
        if self.db_type_hint_label is not None:
            self.db_type_hint_label.configure(text=hint)
        self.toggle_auth_mode()

    def toggle_schedule_mode(self) -> None:
        enabled = self.schedule_enabled_var.get()
        schedule_type = self.schedule_type_var.get()
        time_state = "normal" if enabled and schedule_type == "daily" else "disabled"
        interval_state = "normal" if enabled and schedule_type == "interval" else "disabled"
        if self.schedule_time_entry is not None:
            self.schedule_time_entry.configure(state=time_state)
        if self.schedule_interval_entry is not None:
            self.schedule_interval_entry.configure(state=interval_state)

    def load_config(self, auto: bool = False) -> None:
        if not CONFIG_FILE.exists():
            self.apply_config(AppConfig())
            if not auto:
                self.log("未找到配置文件，已加载默认配置。")
            return
        try:
            saved_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            saved_config.setdefault("db_type", "sqlserver")
            saved_config.setdefault("retention_days", "30")
            config = AppConfig(**saved_config)
            self.apply_config(config)
            if not auto:
                self.log(f"已加载配置文件：{CONFIG_FILE}")
        except Exception as exc:
            self.apply_config(AppConfig())
            self.log(f"加载配置失败：{exc}")
            if not auto:
                messagebox.showerror("加载失败", f"无法读取配置文件：\n{exc}")

    def save_config(self) -> None:
        try:
            config = self.collect_config(validate=False)
            self.validate_retention_config(config)
            self.validate_schedule_config(config)
            CONFIG_FILE.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
            self.sync_startup_state(show_message=False)
            self.log(f"配置已保存到：{CONFIG_FILE}")
            self.status_var.set("配置已保存")
        except Exception as exc:
            self.log(f"保存配置失败：{exc}")
            messagebox.showerror("保存失败", f"无法保存配置文件：\n{exc}")

    def collect_config(self, validate: bool = True) -> AppConfig:
        db_type = self.db_type_var.get()
        config = AppConfig(
            db_type=db_type,
            server=self.server_var.get().strip(),
            port=self.port_var.get().strip() or ("3306" if db_type == "mysql" else "1433"),
            database=self.database_var.get().strip(),
            auth_mode="sql" if db_type == "mysql" else self.auth_mode_var.get(),
            username=self.username_var.get().strip(),
            password=self.password_var.get(),
            backup_dir=self.backup_dir_var.get().strip(),
            backup_name=self.backup_name_var.get().strip(),
            retention_days=self.retention_days_var.get().strip() or "0",
            schedule_enabled=bool(self.schedule_enabled_var.get()),
            schedule_type=self.schedule_type_var.get(),
            schedule_time=self.schedule_time_var.get().strip(),
            schedule_interval_minutes=self.schedule_interval_var.get().strip() or "60",
            minimize_to_tray=bool(self.minimize_to_tray_var.get()),
            start_with_windows=bool(self.start_with_windows_var.get()),
            tray_notifications=bool(self.tray_notifications_var.get()),
            startup_minimized=bool(self.startup_minimized_var.get()),
        )
        if validate:
            if not config.server:
                raise ValueError("请填写服务器/主机地址。")
            if not config.port.isdigit():
                raise ValueError("端口必须是数字。")
            if config.db_type == "mysql" and not config.username:
                raise ValueError("MySQL 需要填写用户名。")
            if config.db_type == "sqlserver" and config.auth_mode == "sql" and (not config.username or not config.password):
                raise ValueError("SQL Server 认证需要填写用户名和密码。")
            if not config.backup_dir:
                raise ValueError("请填写备份目录。")
        if validate:
            self.validate_retention_config(config)
        return config

    def validate_retention_config(self, config: AppConfig) -> None:
        if not config.retention_days.isdigit():
            raise ValueError("备份保留天数必须是数字。")

    def validate_schedule_config(self, config: AppConfig) -> None:
        if not config.schedule_enabled:
            return
        if config.schedule_type not in {"daily", "interval"}:
            raise ValueError("计划类型无效。")
        if config.schedule_type == "daily":
            try:
                datetime.strptime(config.schedule_time, "%H:%M")
            except ValueError as exc:
                raise ValueError("每天时间格式必须是 HH:MM，例如 02:00。") from exc
        if config.schedule_type == "interval":
            if not config.schedule_interval_minutes.isdigit():
                raise ValueError("间隔分钟必须是数字。")
            if int(config.schedule_interval_minutes) <= 0:
                raise ValueError("间隔分钟必须大于 0。")

    def apply_config(self, config: AppConfig) -> None:
        self.db_type_var.set(config.db_type)
        self.server_var.set(config.server)
        self.port_var.set(config.port)
        self.database_var.set(config.database)
        self.auth_mode_var.set(config.auth_mode)
        self.username_var.set(config.username)
        self.password_var.set(config.password)
        self.backup_dir_var.set(config.backup_dir)
        self.backup_name_var.set(config.backup_name)
        self.retention_days_var.set(config.retention_days)
        self.schedule_enabled_var.set(config.schedule_enabled)
        self.schedule_type_var.set(config.schedule_type)
        self.schedule_time_var.set(config.schedule_time)
        self.schedule_interval_var.set(config.schedule_interval_minutes)
        self.minimize_to_tray_var.set(config.minimize_to_tray)
        self.start_with_windows_var.set(config.start_with_windows)
        self.tray_notifications_var.set(config.tray_notifications)
        self.startup_minimized_var.set(config.startup_minimized)
        self.toggle_db_type()
        self.toggle_schedule_mode()

    def should_start_minimized(self) -> bool:
        argv_flags = {arg.lower() for arg in sys.argv[1:]}
        return self.startup_minimized_var.get() and (
            "--startup-minimized" in argv_flags or "--minimized" in argv_flags
        )

    def apply_startup_window_mode(self) -> None:
        if self.should_start_minimized():
            self.hide_to_tray(notify=False)

    def build_connection_string(self, config: AppConfig, database_override: str | None = None) -> str:
        if pyodbc is None:
            raise RuntimeError("未安装 pyodbc，请先执行 `pip install -r requirements.txt`。")
        database_name = database_override if database_override is not None else (config.database or "master")
        driver_name = self.get_odbc_driver()
        parts = [
            f"DRIVER={{{driver_name}}}",
            f"SERVER={config.server},{config.port}",
            f"DATABASE={database_name}",
            "TrustServerCertificate=yes",
        ]
        if config.auth_mode == "windows":
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={config.username}")
            parts.append(f"PWD={config.password}")
        return ";".join(parts) + ";"

    def get_odbc_driver(self) -> str:
        if pyodbc is None:
            raise RuntimeError("未安装 pyodbc，请先执行 `pip install -r requirements.txt`。")
        available_drivers = list(pyodbc.drivers())
        for driver in ["SQL Server", "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]:
            if driver in available_drivers:
                return driver
        if available_drivers:
            raise RuntimeError("未找到 SQL Server ODBC 驱动。当前可用驱动：" + ", ".join(available_drivers))
        raise RuntimeError("未检测到任何 ODBC 驱动，请先安装 SQL Server 或 SQL Server ODBC Driver 17/18。")

    def connect_mysql(self, config: AppConfig, database_override: str | None = None):
        if pymysql is None:
            raise RuntimeError("未安装 PyMySQL，请先执行 `pip install -r requirements.txt`。")
        return pymysql.connect(
            host=config.server,
            port=int(config.port),
            user=config.username,
            password=config.password,
            database=database_override,
            connect_timeout=5,
            charset="utf8mb4",
        )

    def get_mysqldump_path(self) -> str:
        mysqldump_path = shutil.which("mysqldump")
        if not mysqldump_path:
            raise RuntimeError("未找到 mysqldump，请安装 MySQL 客户端工具并将其加入 PATH。")
        return mysqldump_path

    def set_busy(self, busy: bool, status: str) -> None:
        self.is_busy = busy
        self.status_var.set(status)
        self.root.config(cursor="watch" if busy else "")

    def run_async(self, action_name: str, target) -> None:
        if self.is_busy:
            messagebox.showinfo("请稍候", "当前有任务正在执行，请等待完成后再试。")
            return
        self.set_busy(True, f"{action_name}中...")

        def runner() -> None:
            try:
                target()
            except Exception as exc:
                self.log(f"{action_name}失败：{exc}")
                self.root.after(0, lambda: messagebox.showerror(f"{action_name}失败", str(exc)))
                self.notify("操作失败", f"{action_name}失败：{exc}")
            finally:
                self.root.after(0, lambda: self.set_busy(False, "就绪"))

        threading.Thread(target=runner, daemon=True).start()

    def test_connection(self) -> None:
        try:
            config = self.collect_config(validate=True)
        except Exception as exc:
            messagebox.showwarning("配置不完整", str(exc))
            return

        def job() -> None:
            self.log("开始测试数据库连接...")
            if config.db_type == "mysql":
                with self.connect_mysql(config, database_override=config.database or None) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT @@hostname, DATABASE()")
                        server_name, database_name = cursor.fetchone()
                database_name = database_name or "(未选择数据库)"
                self.log(f"MySQL 连接成功。服务器：{server_name}，数据库：{database_name}")
                self.notify("连接成功", f"已成功连接到 MySQL：{database_name}")
            else:
                connection_string = self.build_connection_string(config, database_override=config.database or "master")
                with pyodbc.connect(connection_string, timeout=5) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT @@SERVERNAME, DB_NAME()")
                    server_name, database_name = cursor.fetchone()
                    self.log(f"SQL Server 连接成功。服务器：{server_name}，数据库：{database_name}")
                    self.notify("连接成功", f"已成功连接到数据库：{database_name}")

        self.run_async("连接测试", job)

    def load_databases(self) -> None:
        try:
            config = self.collect_config(validate=False)
            if not config.server:
                raise ValueError("请先填写服务器地址。")
            if not config.port.isdigit():
                raise ValueError("端口必须是数字。")
            if config.db_type == "mysql" and not config.username:
                raise ValueError("MySQL 需要填写用户名。")
            if config.db_type == "sqlserver" and config.auth_mode == "sql" and (not config.username or not config.password):
                raise ValueError("SQL Server 认证需要填写用户名和密码。")
        except Exception as exc:
            messagebox.showwarning("配置不完整", str(exc))
            return

        def job() -> None:
            self.log("正在读取数据库列表...")
            if config.db_type == "mysql":
                with self.connect_mysql(config) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SHOW DATABASES")
                        system_schemas = {"information_schema", "mysql", "performance_schema", "sys"}
                        databases = [row[0] for row in cursor.fetchall() if row[0] not in system_schemas]
            else:
                connection_string = self.build_connection_string(config, database_override="master")
                with pyodbc.connect(connection_string, timeout=5) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT name
                        FROM sys.databases
                        WHERE name NOT IN ('tempdb')
                        ORDER BY name
                        """
                    )
                    databases = [row[0] for row in cursor.fetchall()]

            self.root.after(0, lambda: self.database_combo.configure(values=databases))
            if databases and not self.database_var.get():
                self.root.after(0, lambda: self.database_var.set(databases[0]))
            self.log(f"已读取到 {len(databases)} 个数据库。")
            self.notify("数据库列表已更新", f"已读取到 {len(databases)} 个数据库")

        self.run_async("读取数据库", job)

    def start_backup(self) -> None:
        try:
            config = self.collect_config(validate=True)
            self.validate_schedule_config(config)
            if not config.database:
                raise ValueError("请选择或填写要备份的数据库。")
        except Exception as exc:
            messagebox.showwarning("配置不完整", str(exc))
            return
        self.run_async("数据库备份", lambda: self.perform_backup(config, source="manual", show_message=True))

    def perform_backup(self, config: AppConfig, source: str, show_message: bool) -> None:
        if config.db_type == "mysql":
            self.perform_mysql_backup(config, source, show_message)
        else:
            self.perform_sqlserver_backup(config, source, show_message)
        self.cleanup_old_backups(config)

    def perform_sqlserver_backup(self, config: AppConfig, source: str, show_message: bool) -> None:
        backup_dir = Path(config.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = config.backup_name or f"{config.database}_{timestamp}.bak"
        if not file_name.lower().endswith(".bak"):
            file_name = f"{file_name}.bak"

        backup_file = backup_dir / file_name
        escaped_database = config.database.replace("]", "]]")
        escaped_path = str(backup_file).replace("'", "''")
        sql = (
            f"BACKUP DATABASE [{escaped_database}] "
            f"TO DISK = N'{escaped_path}' "
            "WITH INIT, FORMAT, COMPRESSION, STATS = 10"
        )

        self.log(f"{'定时任务触发备份' if source == 'schedule' else '开始备份数据库'}：{config.database}")
        self.log(f"备份文件：{backup_file}")

        connection_string = self.build_connection_string(config, database_override="master")
        with pyodbc.connect(connection_string, timeout=5, autocommit=True) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            while cursor.nextset():
                pass

        self.log(f"备份完成：{backup_file}")
        self.notify("备份完成", f"{config.database} 已备份到 {backup_file.name}")
        if show_message and not self.is_hidden_to_tray:
            self.root.after(0, lambda: messagebox.showinfo("备份完成", f"数据库 {config.database} 已成功备份到：\n{backup_file}"))

    def perform_mysql_backup(self, config: AppConfig, source: str, show_message: bool) -> None:
        backup_dir = Path(config.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = config.backup_name or f"{config.database}_{timestamp}.sql"
        if not file_name.lower().endswith(".sql"):
            file_name = f"{file_name}.sql"

        backup_file = backup_dir / file_name
        self.log(f"{'定时任务触发备份' if source == 'schedule' else '开始备份数据库'}：{config.database}")
        self.log(f"备份文件：{backup_file}")

        command = [
            self.get_mysqldump_path(),
            "--host",
            config.server,
            "--port",
            config.port,
            "--user",
            config.username,
            "--single-transaction",
            "--routines",
            "--triggers",
            "--events",
            "--databases",
            config.database,
        ]
        env = None
        if config.password:
            env = dict(os.environ, MYSQL_PWD=config.password)

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        with backup_file.open("w", encoding="utf-8", newline="\n") as output_file:
            result = subprocess.run(
                command,
                stdout=output_file,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=False,
                creationflags=creationflags,
            )
        if result.returncode != 0:
            try:
                backup_file.unlink(missing_ok=True)
            except OSError:
                pass
            error_text = result.stderr.strip() or f"mysqldump 退出码：{result.returncode}"
            raise RuntimeError(error_text)

        self.log(f"备份完成：{backup_file}")
        self.notify("备份完成", f"{config.database} 已备份到 {backup_file.name}")
        if show_message and not self.is_hidden_to_tray:
            self.root.after(0, lambda: messagebox.showinfo("备份完成", f"数据库 {config.database} 已成功备份到：\n{backup_file}"))

    def cleanup_old_backups(self, config: AppConfig) -> int:
        if not config.retention_days.isdigit():
            return 0
        retention_days = int(config.retention_days)
        if retention_days <= 0:
            return 0

        backup_dir = Path(config.backup_dir)
        if not backup_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=retention_days)
        removable_suffixes = {".bak", ".sql"}
        removed_count = 0
        removed_names: list[str] = []

        for file_path in backup_dir.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() not in removable_suffixes:
                continue
            try:
                modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            except OSError:
                continue
            if modified_time >= cutoff:
                continue
            try:
                file_path.unlink()
            except OSError as exc:
                self.log(f"清理历史备份失败：{file_path.name}，{exc}")
                continue
            removed_count += 1
            removed_names.append(file_path.name)

        if removed_count:
            self.log(
                f"已清理 {removed_count} 个超过 {retention_days} 天的历史备份："
                + ", ".join(removed_names)
            )
        else:
            self.log(f"未发现超过 {retention_days} 天的历史备份文件")
        return removed_count

    def start_scheduler(self) -> None:
        threading.Thread(target=self.scheduler_loop, daemon=True).start()

    def scheduler_loop(self) -> None:
        while not self.scheduler_stop_event.is_set():
            try:
                self.check_retention_cleanup()
                self.check_schedule()
            except Exception as exc:
                self.log(f"定时任务检查失败：{exc}")
                self.notify("定时任务检查失败", str(exc))
            self.scheduler_stop_event.wait(20)

    def check_retention_cleanup(self) -> None:
        if self.is_busy:
            return
        config = self.collect_config(validate=False)
        try:
            self.validate_retention_config(config)
        except Exception as exc:
            self.log(f"历史备份清理已跳过：{exc}")
            return
        if not config.backup_dir or int(config.retention_days) <= 0:
            return

        cleanup_key = f"{Path(config.backup_dir).resolve()}:{datetime.now().strftime('%Y-%m-%d')}"
        if cleanup_key == self.last_cleanup_key:
            return
        self.last_cleanup_key = cleanup_key

        removed_count = self.cleanup_old_backups(config)
        if removed_count:
            self.notify("历史备份已清理", f"已删除 {removed_count} 个超过 {config.retention_days} 天的备份文件")

    def check_schedule(self) -> None:
        if self.is_busy:
            return
        config = self.collect_config(validate=False)
        if not config.schedule_enabled:
            return
        try:
            self.validate_schedule_config(config)
            self.validate_backup_prerequisites(config)
        except Exception as exc:
            self.log(f"定时备份已跳过：{exc}")
            return

        schedule_key = self.get_current_schedule_key(config)
        if schedule_key is None or schedule_key == self.last_schedule_key:
            return

        self.last_schedule_key = schedule_key
        self.root.after(0, lambda: self.set_busy(True, "定时备份执行中..."))

        def runner() -> None:
            try:
                self.perform_backup(config, source="schedule", show_message=False)
            except Exception as exc:
                self.log(f"定时备份失败：{exc}")
                self.notify("定时备份失败", str(exc))
            finally:
                self.root.after(0, lambda: self.set_busy(False, "就绪"))

        threading.Thread(target=runner, daemon=True).start()

    def validate_backup_prerequisites(self, config: AppConfig) -> None:
        if not config.server:
            raise ValueError("服务器地址未填写。")
        if not config.port.isdigit():
            raise ValueError("端口不是有效数字。")
        if config.db_type == "mysql" and not config.username:
            raise ValueError("MySQL 用户名未填写。")
        if config.db_type == "mysql" and not config.database:
            raise ValueError("未选择要备份的 MySQL 数据库。")
        if config.db_type == "mysql" and not shutil.which("mysqldump"):
            raise ValueError("未找到 mysqldump，请先安装 MySQL 客户端工具。")
        if config.db_type == "sqlserver" and config.auth_mode == "sql" and (not config.username or not config.password):
            raise ValueError("SQL Server 认证缺少用户名或密码。")
        if not config.database:
            raise ValueError("未选择要备份的数据库。")
        if not config.backup_dir:
            raise ValueError("备份目录未填写。")

    def get_current_schedule_key(self, config: AppConfig) -> str | None:
        now = datetime.now()
        if config.schedule_type == "daily":
            trigger_time = datetime.strptime(config.schedule_time, "%H:%M").time()
            if now.hour == trigger_time.hour and now.minute == trigger_time.minute:
                return f"daily:{now.strftime('%Y-%m-%d')}:{config.schedule_time}"
            return None

        interval = int(config.schedule_interval_minutes)
        total_minutes = now.hour * 60 + now.minute
        if total_minutes % interval == 0:
            slot = total_minutes // interval
            return f"interval:{now.strftime('%Y-%m-%d')}:{slot}:{interval}"
        return None

    def setup_tray(self) -> None:
        if not self.tray_available:
            self.log("系统托盘功能不可用，请先安装 pystray 和 Pillow。")
            return

        image = self.create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self.on_tray_show),
            pystray.MenuItem("立即备份", self.on_tray_backup),
            pystray.MenuItem("退出程序", self.on_tray_exit),
        )
        self.tray_icon = pystray.Icon(APP_NAME, image, "数据库备份工具", menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def create_tray_image(self):
        if ICON_PNG_FILE.exists():
            try:
                icon = Image.open(ICON_PNG_FILE).convert("RGBA")
                return icon.resize((64, 64))
            except Exception:
                pass
        image = Image.new("RGBA", (64, 64), (25, 83, 95, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 8, 58, 56), radius=10, fill=(31, 139, 127, 255))
        draw.rectangle((18, 16, 46, 24), fill=(230, 243, 240, 255))
        draw.rectangle((18, 30, 46, 38), fill=(230, 243, 240, 255))
        draw.rectangle((18, 44, 36, 50), fill=(230, 243, 240, 255))
        draw.ellipse((40, 42, 52, 54), fill=(255, 214, 102, 255))
        return image

    def notify(self, title: str, message: str) -> None:
        if not self.tray_notifications_var.get():
            return
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.notify(message, title)
        except Exception:
            pass

    def hide_to_tray(self, notify: bool = True) -> None:
        if not self.tray_available or self.tray_icon is None:
            self.root.iconify()
            return
        self.is_hidden_to_tray = True
        self.root.withdraw()
        self.status_var.set("程序已最小化到系统托盘")
        if not self.tray_hint_shown:
            self.log("程序已最小化到系统托盘，可在托盘菜单中恢复窗口或退出。")
            self.tray_hint_shown = True
        if notify:
            self.notify("程序正在后台运行", "数据库备份工具已最小化到系统托盘")

    def show_from_tray(self) -> None:
        self.is_hidden_to_tray = False
        self.root.deiconify()
        self.root.after(50, self.root.lift)
        self.root.after(100, lambda: self.root.focus_force())
        self.status_var.set("窗口已恢复")

    def on_tray_show(self, icon=None, item=None) -> None:
        self.root.after(0, self.show_from_tray)

    def on_tray_backup(self, icon=None, item=None) -> None:
        self.root.after(0, self.start_backup)

    def on_tray_exit(self, icon=None, item=None) -> None:
        self.root.after(0, self.exit_application)

    def on_window_unmap(self, event) -> None:
        if self.is_exiting:
            return
        if self.root.state() == "iconic" and self.minimize_to_tray_var.get():
            self.root.after(0, self.hide_to_tray)

    def on_close(self) -> None:
        if self.minimize_to_tray_var.get() and self.tray_available:
            self.hide_to_tray()
            return
        self.exit_application()

    def get_startup_command(self) -> str:
        minimized_arg = " --startup-minimized" if self.startup_minimized_var.get() else ""
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"{minimized_arg}'
        return f'"{Path(sys.executable).resolve()}" "{Path(__file__).resolve()}"{minimized_arg}'

    def set_startup_enabled(self, enabled: bool) -> None:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self.get_startup_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass

    def is_startup_enabled(self) -> bool:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return value == self.get_startup_command()
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def sync_startup_state(self, show_message: bool) -> None:
        enabled = self.start_with_windows_var.get()
        try:
            self.set_startup_enabled(enabled)
            state_text = "已启用开机自启动" if enabled else "已关闭开机自启动"
            self.log(state_text)
            if show_message:
                messagebox.showinfo("设置成功", state_text)
        except Exception as exc:
            self.log(f"开机自启动设置失败：{exc}")
            if show_message:
                messagebox.showerror("设置失败", f"无法设置开机自启动：\n{exc}")

    def exit_application(self) -> None:
        if self.is_exiting:
            return
        self.is_exiting = True
        self.scheduler_stop_event.set()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def write_log_file(self, message: str) -> None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as log_file:
                log_file.write(message + "\n")
        except Exception:
            pass

    def process_log_queue(self) -> None:
        if self.is_exiting:
            return
        if self.log_text is not None:
            while not self.log_queue.empty():
                msg = self.log_queue.get_nowait()
                self.write_log_file(msg)
                self.log_text.configure(state="normal")
                self.log_text.insert(END, msg + "\n")
                self.log_text.see(END)
                self.log_text.configure(state="disabled")
                self.status_var.set(msg)
        self.root.after(200, self.process_log_queue)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = SqlServerBackupApp(root)
    app.log("应用已启动。")
    root.mainloop()


if __name__ == "__main__":
    main()
