from __future__ import annotations

import queue
import threading
import time
import tkinter as tk

import customtkinter as ctk

from app import config
from app.models import LyricsResult, SongInfo
from app.services.browser_watcher import BrowserWatcher
from app.services.cache_service import LyricsCache
from app.services.lyrics_service import LyricsService
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
        self.lyrics_service = LyricsService(self.cache)

        self.current_song: SongInfo | None = None
        self.current_lyrics: LyricsResult | None = None
        self.last_requested_key = ""
        self.last_seen_song_at = 0.0
        self.playback_anchor_position = 0.0
        self.playback_anchor_at = time.time()
        self.active_index = -1
        self.current_offset = 0.0
        self.line_items: list[dict] = []
        self.line_width = 0
        self.empty_state: tuple[str, str] = (
            "Buka YouTube Music atau YouTube di Chrome / Edge",
            "Aplikasi akan auto detect lagu dan mencari lirik secara otomatis.",
        )
        self.closing = False
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
        self.status_badge.pack(side="left", padx=(0, 10))

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
            width=120,
            command=self._on_opacity_change,
            button_color=config.COLORS["accent"],
            progress_color=config.COLORS["accent_soft"],
            fg_color="#243041",
        )
        self.opacity_slider.set(config.DEFAULT_OPACITY)
        self.opacity_slider.pack(side="left", padx=(0, 10))

        self.close_button = ctk.CTkButton(
            self.controls,
            text="×",
            width=34,
            height=34,
            command=self.close,
            corner_radius=999,
            fg_color="#26171b",
            hover_color="#3d1e25",
            text_color="#fda4af",
            font=("Segoe UI Variable", 18, "bold"),
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
            text="◢",
            font=("Segoe UI Symbol", 14),
            text_color=config.COLORS["subtle"],
            fg_color="transparent",
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-12)

    def _bind_events(self) -> None:
        drag_widgets = [self.header, self.title_frame, self.song_label, self.meta_label]
        for widget in drag_widgets:
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._do_move)

        self.resize_grip.bind("<ButtonPress-1>", self._start_resize)
        self.resize_grip.bind("<B1-Motion>", self._do_resize)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Configure>", self._handle_configure)

    def _enable_window_effects(self) -> None:
        apply_window_effects(self)

    def _start_move(self, event: tk.Event) -> None:
        self._move_origin = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _do_move(self, event: tk.Event) -> None:
        if not self._move_origin:
            return
        offset_x, offset_y = self._move_origin
        self.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _start_resize(self, event: tk.Event) -> None:
        self._resize_origin = (
            event.x_root,
            event.y_root,
            self.winfo_width(),
            self.winfo_height(),
        )

    def _do_resize(self, event: tk.Event) -> None:
        if not self._resize_origin:
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

        self.after(config.QUEUE_POLL_MS, self._pump_events)

    def _handle_song_state(self, song: SongInfo | None) -> None:
        now = time.time()

        if song is None:
            if self.current_song and now - self.last_seen_song_at < 5:
                return

            self.current_song = None
            self.current_lyrics = None
            self.active_index = -1
            self.line_items.clear()
            self.empty_state = (
                "Buka YouTube Music atau YouTube di Chrome / Edge",
                "Jika lagu sudah terbuka tapi belum terdeteksi, pastikan browser menampilkan metadata media.",
            )
            self._set_status("Menunggu browser...", detection="idle")
            self._render_empty_state(*self.empty_state)
            self._refresh_target_opacity()
            return

        self.last_seen_song_at = now
        self.playback_anchor_position = max(song.position_seconds, 0.0)
        self.playback_anchor_at = now

        current_key = self.current_song.cache_key() if self.current_song else ""
        next_key = song.cache_key()
        self.current_song = song
        self._refresh_target_opacity()

        self.song_label.configure(text=song.display_title)

        if song.detection_method == "media_session":
            subtitle = "Windows Media Session aktif"
        else:
            subtitle = "Fallback judul tab browser"
        self.meta_label.configure(text=subtitle)

        if current_key == next_key and self.current_lyrics:
            self._set_status("Lirik aktif", detection=song.detection_method)
            return

        if current_key == next_key and self.last_requested_key == next_key:
            return

        self.current_lyrics = None
        self.active_index = -1
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

    def _handle_lyrics_loaded(self, payload: dict) -> None:
        if not self.current_song:
            return

        song_key = payload.get("song_key")
        if song_key != self.current_song.cache_key():
            return

        result = payload.get("result")
        source = str(payload.get("source", ""))

        if result is None:
            self.current_lyrics = None
            self.active_index = -1
            self._set_status("Lirik tidak ditemukan", detection=self.current_song.detection_method)
            self.empty_state = (
                "Lirik tidak ditemukan",
                source or "Coba ganti lagu lain atau biarkan aplikasi mendeteksi ulang saat track berganti.",
            )
            self._render_empty_state(*self.empty_state)
            return

        self.current_lyrics = result
        self.song_label.configure(text=result.display_title)

        badge = "Synced" if result.synced else "Plain lyrics"
        if source == "cache":
            badge = f"{badge} • cache"
        self._set_status(badge, detection=self.current_song.detection_method)
        self._render_lyrics(result)

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

        if self.current_lyrics.synced:
            next_active = self._find_active_index(playback_position)
        else:
            next_active = -1

        target_index = max(next_active, 0)
        if target_index >= len(self.line_items):
            target_index = len(self.line_items) - 1

        base_y = self.line_items[target_index]["base_y"]
        desired_offset = (canvas_height * 0.42) - base_y
        self.current_offset += (desired_offset - self.current_offset) * 0.18

        if force or next_active != self.active_index:
            self.active_index = next_active
            self._apply_line_styles()

        for item in self.line_items:
            item_id = item["id"]
            self.canvas.coords(item_id, canvas_width / 2, item["base_y"] + self.current_offset)
            if self.line_width != max(260, canvas_width - 90):
                self.canvas.itemconfigure(item_id, width=max(260, canvas_width - 90))

        self.line_width = max(260, canvas_width - 90)

    def _apply_line_styles(self) -> None:
        for item in self.line_items:
            item_id = item["id"]
            index = item["index"]

            if self.active_index == -1:
                fill = config.COLORS["past"] if index < 6 else config.COLORS["future"]
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

    def _find_active_index(self, position_seconds: float) -> int:
        if not self.current_lyrics:
            return -1

        lines = self.current_lyrics.lines
        for index, line in enumerate(lines):
            if line.start_time is None:
                continue

            end_time = line.end_time if line.end_time is not None else line.start_time + 4.5
            if line.start_time <= position_seconds < end_time:
                return index

        if lines and lines[-1].start_time is not None and position_seconds >= lines[-1].start_time:
            return len(lines) - 1
        return -1

    def _handle_configure(self, _event: tk.Event) -> None:
        current_size = (self.winfo_width(), self.winfo_height())
        if current_size == self._last_size:
            return

        self._last_size = current_size
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

