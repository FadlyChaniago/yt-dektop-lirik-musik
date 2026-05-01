from __future__ import annotations

import ctypes
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app import config
from app.models import LyricsResult, SongInfo
from app.services.browser_watcher import BrowserWatcher
from app.services.cache_service import LyricsCache
from app.services.lyrics_service import LyricsService
from app.services.translation_service import LyricsTranslationService
from app.utils.windows_effects import apply_window_effects


class LyricsOverlayApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        super().__init__()

        self.title(config.APP_NAME)
        self.geometry(f"{config.WINDOW_WIDTH}x{config.WINDOW_HEIGHT}+80+80")
        self.minsize(config.MIN_WINDOW_WIDTH, config.MIN_WINDOW_HEIGHT)
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        self.current_alpha = config.IDLE_OPACITY
        self.target_alpha = config.IDLE_OPACITY
        self.user_opacity = config.DEFAULT_OPACITY
        self.attributes("-alpha", self.current_alpha)
        self.configure(fg_color=config.COLORS["window"])

        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.browser_watcher = BrowserWatcher(self.event_queue.put)
        self.cache = LyricsCache(config.CACHE_FILE)
        self.translation_cache = LyricsCache(config.TRANSLATION_CACHE_FILE)
        self.lyrics_service = LyricsService(self.cache)
        self.translation_service = LyricsTranslationService(self.translation_cache)

        self.current_song: SongInfo | None = None
        self.original_lyrics: LyricsResult | None = None
        self.original_lyrics_source = ""
        self.current_lyrics: LyricsResult | None = None
        self.current_lyrics_source = ""
        self.current_lyrics_is_translation = False
        self.last_requested_key = ""
        self.last_seen_song_at = 0.0
        self.playback_anchor_position = 0.0
        self.playback_anchor_at = time.time()
        self.active_index = -1
        self.current_offset = 0.0
        self.follow_live = True
        self.line_items: list[dict] = []
        self.line_width = 0
        self.language_mode = "original"
        self.text_only_mode = False
        self.empty_state: tuple[str, str] = (
            "Buka YouTube Music atau YouTube di Chrome / Edge",
            "Aplikasi akan auto detect lagu dan mencari lirik secara otomatis.",
        )
        self.closing = False
        self.is_maximized = False
        self.is_minimized = False
        self.restore_geometry = self.geometry()
        self._move_origin: tuple[int, int] | None = None
        self._resize_origin: tuple[int, int, int, int] | None = None
        self._resize_after_id: str | None = None
        self._last_size = (0, 0)

        self.font_title = ("Segoe UI Variable", 15, "bold")
        self.font_meta = ("Segoe UI Variable", 11)
        self.font_line = ("Segoe UI Variable", 22)
        self.font_line_active = ("Segoe UI Variable", 28, "bold")

        self._build_ui()
        self._bind_events()
        self._set_status("Menunggu browser...", detection="idle")
        self._render_empty_state(*self.empty_state)
        self._update_language_button()
        self._update_view_button()
        self._update_maximize_button()

        self.after(120, self._enable_window_effects)
        self.after(config.QUEUE_POLL_MS, self._pump_events)
        self.after(config.UI_TICK_MS, self._ui_tick)
        self.after(24, self._animate_alpha)

        self.browser_watcher.start()

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.shell = ctk.CTkFrame(
            self,
            corner_radius=28,
            fg_color=config.COLORS["panel"],
            border_width=1,
            border_color=config.COLORS["panel_border"],
        )
        self.shell.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        self.shell.grid_rowconfigure(1, weight=1)
        self.shell.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkFrame(
            self.shell,
            corner_radius=20,
            fg_color=config.COLORS["panel_soft"],
            height=70,
        )
        self.header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        self.header.grid_columnconfigure(0, weight=1)

        self.title_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="w", padx=(14, 10), pady=12)

        self.song_label = ctk.CTkLabel(
            self.title_frame,
            text=config.APP_NAME,
            font=self.font_title,
            text_color=config.COLORS["text"],
            anchor="w",
        )
        self.song_label.pack(anchor="w")

        self.meta_label = ctk.CTkLabel(
            self.title_frame,
            text="Realtime lyric overlay untuk YouTube / YouTube Music",
            font=self.font_meta,
            text_color=config.COLORS["muted"],
            anchor="w",
        )
        self.meta_label.pack(anchor="w", pady=(2, 0))

        self.controls = ctk.CTkFrame(self.header, fg_color="transparent")
        self.controls.grid(row=0, column=1, sticky="e", padx=(10, 14), pady=10)

        self.status_badge = ctk.CTkLabel(
            self.controls,
            text="Idle",
            corner_radius=999,
            fg_color="#16202c",
            text_color=config.COLORS["accent"],
            font=("Segoe UI Variable", 11, "bold"),
            padx=12,
            pady=6,
        )
        self.status_badge.pack(side="left", padx=(0, 8))

        self.refresh_button = self._build_header_button(
            text="Refresh",
            width=76,
            command=self._reload_current_song,
        )
        self.refresh_button.pack(side="left", padx=(0, 8))

        self.language_button = self._build_header_button(
            text="Terjemah ID",
            width=96,
            command=self._toggle_language_mode,
        )
        self.language_button.pack(side="left", padx=(0, 8))

        self.view_button = self._build_header_button(
            text="Text Only",
            width=86,
            command=self._toggle_text_only_mode,
        )
        self.view_button.pack(side="left", padx=(0, 10))

        self.live_button = self._build_header_button(
            text="Live On",
            width=74,
            command=self._toggle_live_follow,
        )
        self.live_button.pack(side="left", padx=(0, 10))

        self.opacity_label = ctk.CTkLabel(
            self.controls,
            text="Opacity",
            font=self.font_meta,
            text_color=config.COLORS["muted"],
        )
        self.opacity_label.pack(side="left", padx=(0, 8))

        self.opacity_slider = ctk.CTkSlider(
            self.controls,
            from_=0.45,
            to=1.0,
            number_of_steps=11,
            width=100,
            command=self._on_opacity_change,
            button_color=config.COLORS["accent"],
            progress_color=config.COLORS["accent_soft"],
            fg_color="#243041",
        )
        self.opacity_slider.set(config.DEFAULT_OPACITY)
        self.opacity_slider.pack(side="left", padx=(0, 10))

        self.minimize_button = self._build_window_button(
            text="-",
            width=34,
            command=self._minimize_window,
            fg_color="#16202c",
            hover_color="#223043",
            text_color=config.COLORS["text"],
        )
        self.minimize_button.pack(side="left", padx=(0, 6))

        self.maximize_button = self._build_window_button(
            text="Max",
            width=52,
            command=self._toggle_maximize,
            fg_color="#16202c",
            hover_color="#223043",
            text_color=config.COLORS["text"],
        )
        self.maximize_button.pack(side="left", padx=(0, 6))

        self.close_button = ctk.CTkButton(
            self.controls,
            text="X",
            width=34,
            height=34,
            command=self.close,
            corner_radius=999,
            fg_color="#26171b",
            hover_color="#3d1e25",
            text_color="#fda4af",
            font=("Segoe UI Variable", 14, "bold"),
        )
        self.close_button.pack(side="left")

        self.content = ctk.CTkFrame(
            self.shell,
            corner_radius=24,
            fg_color="#0c1017",
        )
        self.content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self.content,
            bg="#0c1017",
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.resize_grip = ctk.CTkLabel(
            self.shell,
            text="//",
            font=("Consolas", 11, "bold"),
            text_color=config.COLORS["subtle"],
            fg_color="transparent",
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-12)

    def _build_header_button(self, text: str, width: int, command: Callable[[], None]) -> ctk.CTkButton:
        return ctk.CTkButton(
            self.controls,
            text=text,
            width=width,
            height=34,
            command=command,
            corner_radius=999,
            fg_color="#1b2432",
            hover_color="#243041",
            text_color=config.COLORS["text"],
            font=("Segoe UI Variable", 11, "bold"),
        )

    def _build_window_button(
        self,
        text: str,
        width: int,
        command: Callable[[], None],
        *,
        fg_color: str,
        hover_color: str,
        text_color: str,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            self.controls,
            text=text,
            width=width,
            height=34,
            command=command,
            corner_radius=999,
            fg_color=fg_color,
            hover_color=hover_color,
            text_color=text_color,
            font=("Segoe UI Variable", 11, "bold"),
        )

    def _bind_events(self) -> None:
        drag_widgets = [
            self.header,
            self.title_frame,
            self.song_label,
            self.meta_label,
            self.content,
            self.canvas,
        ]
        for widget in drag_widgets:
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._do_move)
            widget.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())
            widget.bind("<MouseWheel>", self._on_mousewheel)

        self.resize_grip.bind("<ButtonPress-1>", self._start_resize)
        self.resize_grip.bind("<B1-Motion>", self._do_resize)
        self.canvas.bind("<Double-Button-1>", lambda _event: self._toggle_text_only_mode())
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Control-m>", lambda _event: self._toggle_text_only_mode())
        self.bind("<Control-l>", lambda _event: self._toggle_live_follow())
        self.bind("<Control-r>", lambda _event: self._reload_current_song())
        self.bind("<Control-t>", lambda _event: self._toggle_language_mode())
        self.bind("<Control-w>", lambda _event: self._toggle_maximize())
        self.bind("<Unmap>", self._handle_unmap)
        self.bind("<Map>", self._handle_map)
        self.bind("<Configure>", self._handle_configure)

    def _enable_window_effects(self) -> None:
        apply_window_effects(self)

    def _start_move(self, event: tk.Event) -> None:
        if self.is_maximized:
            pointer_ratio = event.x_root / max(self.winfo_width(), 1)
            self._toggle_maximize()
            restored_width = max(self.winfo_width(), config.MIN_WINDOW_WIDTH)
            offset_x = int(restored_width * min(max(pointer_ratio, 0.15), 0.85))
            self._move_origin = (offset_x, event.y_root - self.winfo_y())
            self.geometry(f"+{event.x_root - offset_x}+{self.winfo_y()}")
            return

        self._move_origin = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _do_move(self, event: tk.Event) -> None:
        if not self._move_origin:
            return
        offset_x, offset_y = self._move_origin
        self.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _start_resize(self, event: tk.Event) -> None:
        if self.is_maximized:
            return
        self._resize_origin = (
            event.x_root,
            event.y_root,
            self.winfo_width(),
            self.winfo_height(),
        )

    def _do_resize(self, event: tk.Event) -> None:
        if not self._resize_origin or self.is_maximized:
            return

        start_x, start_y, start_width, start_height = self._resize_origin
        width_delta = event.x_root - start_x
        height_delta = event.y_root - start_y

        next_width = max(config.MIN_WINDOW_WIDTH, start_width + width_delta)
        next_height = max(config.MIN_WINDOW_HEIGHT, start_height + height_delta)
        self.geometry(f"{int(next_width)}x{int(next_height)}+{self.winfo_x()}+{self.winfo_y()}")

    def _on_opacity_change(self, value: float) -> None:
        self.user_opacity = float(value)
        self._refresh_target_opacity()

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        if not self.current_lyrics or not self.line_items:
            return None

        delta = getattr(event, "delta", 0)
        if not delta:
            return None

        self.follow_live = False
        self._update_live_button()
        self.current_offset += (delta / 120.0) * 42.0
        self._reposition_line_items()
        return "break"

    def _refresh_target_opacity(self) -> None:
        if self.closing:
            self.target_alpha = 0.0
            return

        if self.current_song or self.current_lyrics:
            self.target_alpha = self.user_opacity
        else:
            self.target_alpha = max(config.IDLE_OPACITY, self.user_opacity * 0.78)

    def _animate_alpha(self) -> None:
        delta = self.target_alpha - self.current_alpha
        if abs(delta) > 0.01:
            self.current_alpha += delta * 0.22
            self.current_alpha = max(0.0, min(1.0, self.current_alpha))
            self.attributes("-alpha", self.current_alpha)
        else:
            self.current_alpha = self.target_alpha
            self.attributes("-alpha", self.current_alpha)

        if self.closing and self.current_alpha <= 0.03:
            self.browser_watcher.stop()
            self.destroy()
            return

        self.after(24, self._animate_alpha)

    def _pump_events(self) -> None:
        while True:
            try:
                payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if payload.get("type") == "song_state":
                self._handle_song_state(payload.get("song"))
            elif payload.get("type") == "lyrics_loaded":
                self._handle_lyrics_loaded(payload)
            elif payload.get("type") == "translation_loaded":
                self._handle_translation_loaded(payload)

        self.after(config.QUEUE_POLL_MS, self._pump_events)

    def _handle_song_state(self, song: SongInfo | None) -> None:
        now = time.time()
        current_key = self.current_song.cache_key() if self.current_song else ""

        if song is None:
            if self.current_song and now - self.last_seen_song_at < 5:
                return

            self.current_song = None
            self.original_lyrics = None
            self.original_lyrics_source = ""
            self.current_lyrics = None
            self.current_lyrics_source = ""
            self.current_lyrics_is_translation = False
            self.active_index = -1
            self.line_items.clear()
            self.follow_live = False
            self._update_live_button()
            self.empty_state = (
                "Buka YouTube Music atau YouTube di Chrome / Edge",
                "Jika lagu sudah terbuka tapi belum terdeteksi, pastikan browser menampilkan metadata media.",
            )
            self._set_status("Menunggu browser...", detection="idle")
            self._render_empty_state(*self.empty_state)
            self._refresh_target_opacity()
            return

        next_key = song.cache_key()
        same_song = current_key == next_key and bool(next_key)
        expected_position = self._get_estimated_anchor_position(now)

        self.last_seen_song_at = now

        if song.detection_method == "media_session":
            self.playback_anchor_position = self._resolve_media_session_position(
                song=song,
                same_song=same_song,
                expected_position=expected_position,
            )
            self.playback_anchor_at = now
        elif not same_song:
            # Fallback judul tab tidak punya posisi playback, jadi anchor hanya di-reset saat lagu berganti.
            self.playback_anchor_position = 0.0
            self.playback_anchor_at = now

        self.current_song = song
        self._refresh_target_opacity()

        self.song_label.configure(text=song.display_title)

        if song.detection_method == "media_session":
            subtitle = "Sinkron dari Windows Media Session"
        else:
            subtitle = "Fallback judul tab browser"
        self.meta_label.configure(text=subtitle)

        if same_song and self.current_lyrics:
            self._refresh_current_status()
            return

        if same_song and self.last_requested_key == next_key:
            return

        self.original_lyrics = None
        self.original_lyrics_source = ""
        self.current_lyrics = None
        self.current_lyrics_source = ""
        self.current_lyrics_is_translation = False
        self.active_index = -1
        self.follow_live = False
        self._update_live_button()
        self._set_status("Mencari lirik...", detection=song.detection_method)
        self._render_empty_state(
            "Mencari lirik...",
            f"Mencocokkan lagu: {song.display_title}",
        )
        self._request_lyrics(song)

    def _request_lyrics(self, song: SongInfo) -> None:
        song_key = song.cache_key()
        self.last_requested_key = song_key

        def worker() -> None:
            result, source = self.lyrics_service.get_lyrics(song)
            self.event_queue.put(
                {
                    "type": "lyrics_loaded",
                    "song_key": song_key,
                    "result": result,
                    "source": source,
                }
            )

        threading.Thread(target=worker, daemon=True).start()

    def _request_translation(self, lyrics: LyricsResult, song_key: str) -> None:
        def worker() -> None:
            result, source = self.translation_service.translate_lyrics(
                lyrics,
                target_language="id",
            )
            self.event_queue.put(
                {
                    "type": "translation_loaded",
                    "song_key": song_key,
                    "result": result,
                    "source": source,
                    "target_language": "id",
                }
            )

        threading.Thread(target=worker, daemon=True).start()

    def _handle_lyrics_loaded(self, payload: dict) -> None:
        if not self.current_song:
            return

        song_key = payload.get("song_key")
        if song_key != self.current_song.cache_key():
            return

        result = payload.get("result")
        source = str(payload.get("source", ""))

        if result is None:
            self.original_lyrics = None
            self.current_lyrics = None
            self.current_lyrics_source = ""
            self.current_lyrics_is_translation = False
            self.active_index = -1
            self.follow_live = False
            self._update_live_button()
            self._set_status("Lirik tidak ditemukan", detection=self.current_song.detection_method)
            self.empty_state = (
                "Lirik tidak ditemukan",
                source or "Coba ganti lagu lain atau tekan Refresh untuk mencoba lagi.",
            )
            self._render_empty_state(*self.empty_state)
            return

        self.original_lyrics = result
        self.original_lyrics_source = source

        if self.language_mode == "id":
            self._show_lyrics(result, source=source, translated=False)
            self._set_status("Menerjemahkan ID...", detection=self.current_song.detection_method)
            self._request_translation(result, song_key)
            return

        self._show_lyrics(result, source=source, translated=False)

    def _handle_translation_loaded(self, payload: dict) -> None:
        if not self.current_song:
            return

        song_key = payload.get("song_key")
        if song_key != self.current_song.cache_key():
            return

        if payload.get("target_language") != "id":
            return

        result = payload.get("result")
        source = str(payload.get("source", ""))

        if result is None:
            self.language_mode = "original"
            self._update_language_button()
            if self.original_lyrics:
                self._show_lyrics(self.original_lyrics, source=self.original_lyrics_source or "network", translated=False)
            self._set_status("Terjemah gagal", detection=self.current_song.detection_method)
            return

        if self.language_mode != "id":
            return

        self._show_lyrics(result, source=source, translated=True)

    def _show_lyrics(self, lyrics: LyricsResult, *, source: str, translated: bool) -> None:
        self.current_lyrics = lyrics
        self.current_lyrics_source = source
        self.current_lyrics_is_translation = translated
        self.follow_live = lyrics.has_timing
        self.song_label.configure(text=lyrics.display_title)
        self._update_live_button()
        self._refresh_current_status()
        self._render_lyrics(lyrics)

    def _refresh_current_status(self) -> None:
        if not self.current_song or not self.current_lyrics:
            return

        if self.current_lyrics_is_translation:
            badge = "Lirik ID"
        elif self.current_lyrics.timing_mode == "synced":
            badge = "Sinkron"
        elif self.current_lyrics.timing_mode == "estimated":
            badge = "Auto sync"
        else:
            badge = "Teks"

        if self.current_lyrics_source == "cache":
            badge = f"{badge} (cache)"
        self._set_status(badge, detection=self.current_song.detection_method)

    def _set_status(self, text: str, detection: str) -> None:
        badge_colors = {
            "media_session": ("#13212a", config.COLORS["accent"]),
            "window_title": ("#1f1a0f", "#fbbf24"),
            "idle": ("#18212e", config.COLORS["muted"]),
        }
        fg_color, text_color = badge_colors.get(detection, ("#18212e", config.COLORS["muted"]))
        self.status_badge.configure(text=text, fg_color=fg_color, text_color=text_color)

    def _render_empty_state(self, headline: str, detail: str) -> None:
        self.canvas.delete("all")
        self.line_items.clear()

        width = max(self.canvas.winfo_width(), config.MIN_WINDOW_WIDTH)
        height = max(self.canvas.winfo_height(), 220)

        self.canvas.create_text(
            width / 2,
            height / 2 - 14,
            text=headline,
            fill=config.COLORS["text"],
            font=("Segoe UI Variable", 22, "bold"),
            anchor="center",
            width=width - 80,
            justify="center",
        )
        self.canvas.create_text(
            width / 2,
            height / 2 + 26,
            text=detail,
            fill=config.COLORS["muted"],
            font=("Segoe UI Variable", 12),
            anchor="center",
            width=width - 100,
            justify="center",
        )

    def _render_lyrics(self, lyrics: LyricsResult) -> None:
        self.canvas.delete("all")
        self.line_items.clear()
        self.active_index = -1
        self.current_offset = 0.0

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            self.after(120, lambda: self._render_lyrics(lyrics))
            return

        text_width = max(260, width - 90)
        current_y = config.LYRIC_TOP_PADDING

        for index, line in enumerate(lyrics.lines):
            item_id = self.canvas.create_text(
                width / 2,
                current_y,
                text=line.text,
                fill=config.COLORS["future"],
                font=self.font_line,
                anchor="n",
                justify="center",
                width=text_width,
            )
            bbox = self.canvas.bbox(item_id)
            line_height = (bbox[3] - bbox[1]) if bbox else 30
            self.line_items.append(
                {
                    "id": item_id,
                    "base_y": current_y,
                    "height": line_height,
                    "index": index,
                }
            )
            current_y += line_height + config.LYRIC_LINE_SPACING

        self.line_width = text_width
        self._update_karaoke_frame(force=True)

    def _ui_tick(self) -> None:
        self._update_karaoke_frame(force=False)
        self.after(config.UI_TICK_MS, self._ui_tick)

    def _update_karaoke_frame(self, force: bool) -> None:
        if not self.current_lyrics or not self.line_items:
            return

        canvas_width = max(self.canvas.winfo_width(), config.MIN_WINDOW_WIDTH)
        canvas_height = max(self.canvas.winfo_height(), 220)
        playback_position = self._get_current_playback_position()

        if self.current_lyrics.has_timing:
            next_active = self._find_active_index(playback_position)
        else:
            next_active = -1

        target_index = max(next_active, 0)
        if target_index >= len(self.line_items):
            target_index = len(self.line_items) - 1

        if self.current_lyrics.has_timing and self.follow_live:
            base_y = self.line_items[target_index]["base_y"]
            desired_offset = (canvas_height * 0.42) - base_y
            self.current_offset += (desired_offset - self.current_offset) * 0.18

        if force or next_active != self.active_index:
            self.active_index = next_active
            self._apply_line_styles()

        self._reposition_line_items(canvas_width)

    def _reposition_line_items(self, canvas_width: int | None = None) -> None:
        if not self.line_items:
            return

        target_width = canvas_width if canvas_width is not None else max(
            self.canvas.winfo_width(),
            config.MIN_WINDOW_WIDTH,
        )
        next_line_width = max(260, target_width - 90)

        for item in self.line_items:
            item_id = item["id"]
            self.canvas.coords(item_id, target_width / 2, item["base_y"] + self.current_offset)
            if self.line_width != next_line_width:
                self.canvas.itemconfigure(item_id, width=next_line_width)

        self.line_width = next_line_width

    def _apply_line_styles(self) -> None:
        for item in self.line_items:
            item_id = item["id"]
            index = item["index"]

            if self.active_index == -1:
                fill = config.COLORS["future"]
                font = self.font_line
            elif index == self.active_index:
                fill = config.COLORS["highlight"]
                font = self.font_line_active
            elif index < self.active_index:
                fill = config.COLORS["past"]
                font = self.font_line
            else:
                distance = index - self.active_index
                fill = config.COLORS["future"] if distance <= 3 else config.COLORS["inactive"]
                font = self.font_line

            self.canvas.itemconfigure(item_id, fill=fill, font=font)

    def _get_current_playback_position(self) -> float:
        if not self.current_song:
            return 0.0

        if not self.current_song.is_playing:
            return self.playback_anchor_position

        elapsed = max(0.0, time.time() - self.playback_anchor_at)
        position = self.playback_anchor_position + elapsed

        if self.current_song.duration_seconds:
            return min(position, self.current_song.duration_seconds)
        return position

    def _get_estimated_anchor_position(self, now: float) -> float:
        if not self.current_song:
            return 0.0

        if not self.current_song.is_playing:
            return self.playback_anchor_position

        elapsed = max(0.0, now - self.playback_anchor_at)
        estimated = self.playback_anchor_position + elapsed
        if self.current_song.duration_seconds:
            return min(estimated, self.current_song.duration_seconds)
        return estimated

    def _resolve_media_session_position(
        self,
        *,
        song: SongInfo,
        same_song: bool,
        expected_position: float,
    ) -> float:
        reported_position = max(song.position_seconds, 0.0)
        if not same_song:
            return reported_position

        if not song.is_playing:
            return reported_position

        # Beberapa browser kadang mengirim posisi 0 / mundur sebentar walau lagu sedang jalan.
        if expected_position >= 12.0 and reported_position <= 1.0:
            return expected_position

        if reported_position + 3.5 < expected_position:
            return expected_position

        return reported_position

    def _find_active_index(self, position_seconds: float) -> int:
        if not self.current_lyrics:
            return -1

        lines = self.current_lyrics.lines
        first_timed_index = -1
        last_started_index = -1

        for index, line in enumerate(lines):
            if line.start_time is None:
                continue

            if first_timed_index == -1:
                first_timed_index = index

            if position_seconds < line.start_time:
                if last_started_index != -1:
                    return last_started_index
                return first_timed_index

            last_started_index = index
            end_time = line.end_time if line.end_time is not None else line.start_time + 4.5
            if line.start_time <= position_seconds < end_time:
                return index

        return last_started_index

    def _reload_current_song(self) -> None:
        if not self.current_song:
            return

        song = self.current_song
        self.lyrics_service.invalidate(song)
        self.last_requested_key = ""
        self.original_lyrics = None
        self.original_lyrics_source = ""
        self.current_lyrics = None
        self.current_lyrics_source = ""
        self.current_lyrics_is_translation = False
        self.active_index = -1
        self.follow_live = False
        self._update_live_button()
        self._set_status("Refresh lirik...", detection=song.detection_method)
        self._render_empty_state(
            "Memuat ulang lirik...",
            f"Mencocokkan ulang lagu: {song.display_title}",
        )
        self._request_lyrics(song)

    def _minimize_window(self) -> None:
        if self.closing or self.is_minimized:
            return

        self.is_minimized = True
        self.overrideredirect(False)
        self.iconify()

    def _toggle_maximize(self) -> None:
        if self.is_minimized:
            self.deiconify()
            return

        if self.is_maximized:
            self.is_maximized = False
            self.geometry(self.restore_geometry)
        else:
            self.restore_geometry = self.geometry()
            self.geometry(self._get_maximized_geometry())
            self.is_maximized = True

        self._update_maximize_button()
        self._rerender_after_resize()

    def _update_maximize_button(self) -> None:
        if self.is_maximized:
            self.maximize_button.configure(text="Restore", width=68)
        else:
            self.maximize_button.configure(text="Max", width=52)

    def _get_maximized_geometry(self) -> str:
        try:
            rect = ctypes.wintypes.RECT()  # type: ignore[attr-defined]
            result = ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
            if result:
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                return f"{width}x{height}+{rect.left}+{rect.top}"
        except Exception:
            pass

        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        return f"{width}x{height}+0+0"

    def _toggle_language_mode(self) -> None:
        if self.language_mode == "id":
            self.language_mode = "original"
            self._update_language_button()
            if self.original_lyrics:
                self._show_lyrics(self.original_lyrics, source=self.original_lyrics_source or "network", translated=False)
            return

        self.language_mode = "id"
        self._update_language_button()
        if not self.original_lyrics or not self.current_song:
            return

        self._set_status("Menerjemahkan ID...", detection=self.current_song.detection_method)
        self._request_translation(self.original_lyrics, self.current_song.cache_key())

    def _toggle_live_follow(self) -> None:
        if not self.current_lyrics or not self.current_lyrics.has_timing:
            return

        self.follow_live = not self.follow_live
        self._update_live_button()
        if self.follow_live:
            self._update_karaoke_frame(force=True)

    def _update_live_button(self) -> None:
        if not self.current_lyrics or not self.current_lyrics.has_timing:
            self.live_button.configure(
                text="Live Off",
                fg_color="#273041",
                hover_color="#273041",
                text_color=config.COLORS["subtle"],
            )
            return

        if self.follow_live:
            self.live_button.configure(
                text="Live On",
                fg_color="#1d3b2a",
                hover_color="#285238",
                text_color=config.COLORS["text"],
            )
        else:
            self.live_button.configure(
                text="Live Off",
                fg_color="#3a2418",
                hover_color="#4d2f1f",
                text_color=config.COLORS["text"],
            )

    def _update_language_button(self) -> None:
        if self.language_mode == "id":
            self.language_button.configure(
                text="Teks Asli",
                fg_color="#1d3b2a",
                hover_color="#285238",
            )
        else:
            self.language_button.configure(
                text="Terjemah ID",
                fg_color="#1b2432",
                hover_color="#243041",
            )

    def _toggle_text_only_mode(self) -> None:
        self.text_only_mode = not self.text_only_mode
        if self.text_only_mode:
            self.header.grid_remove()
            self.resize_grip.place_forget()
            self.shell.configure(
                fg_color="#0b1017",
                border_width=0,
                border_color="#0b1017",
                corner_radius=24,
            )
            self.shell.grid_configure(padx=8, pady=8)
            self.content.grid_configure(padx=8, pady=8)
        else:
            self.header.grid()
            self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-12)
            self.shell.configure(
                fg_color=config.COLORS["panel"],
                border_width=1,
                border_color=config.COLORS["panel_border"],
                corner_radius=28,
            )
            self.shell.grid_configure(padx=18, pady=18)
            self.content.grid_configure(padx=16, pady=(0, 16))

        self._update_view_button()
        self._rerender_after_resize()

    def _update_view_button(self) -> None:
        if self.text_only_mode:
            self.view_button.configure(
                text="Normal",
                fg_color="#1d3b2a",
                hover_color="#285238",
            )
        else:
            self.view_button.configure(
                text="Text Only",
                fg_color="#1b2432",
                hover_color="#243041",
            )

    def _handle_unmap(self, _event: tk.Event) -> None:
        if self.state() == "iconic":
            self.is_minimized = True

    def _handle_map(self, _event: tk.Event) -> None:
        if self.is_minimized:
            self.after(10, self._restore_after_minimize)

    def _restore_after_minimize(self) -> None:
        self.is_minimized = False
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.after(60, self._enable_window_effects)

    def _handle_configure(self, _event: tk.Event) -> None:
        current_size = (self.winfo_width(), self.winfo_height())
        if current_size == self._last_size:
            return

        self._last_size = current_size
        if not self.is_maximized and self.state() == "normal":
            self.restore_geometry = self.geometry()
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(120, self._rerender_after_resize)

    def _rerender_after_resize(self) -> None:
        self._resize_after_id = None
        if self.current_lyrics:
            self._render_lyrics(self.current_lyrics)
        else:
            self._render_empty_state(*self.empty_state)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.target_alpha = 0.0

    def run(self) -> None:
        self.mainloop()
