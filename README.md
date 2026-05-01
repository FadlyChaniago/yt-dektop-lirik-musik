# Desktop Musik Lirik

Overlay desktop Windows modern berbasis `Python + CustomTkinter` untuk menampilkan lirik lagu YouTube / YouTube Music secara realtime.

## Fitur

- Overlay transparan dan `always on top`
- Dark mode, rounded corner, drag to move, resize, dan opacity slider
- Auto detect lagu dari `Windows Media Session`
- Fallback baca judul tab YouTube / YouTube Music dari Chrome / Edge via `PyGetWindow`
- Auto fetch lirik dari internet via `LRCLIB`
- Karaoke highlight untuk line aktif
- Smooth lyric scrolling
- Cache lirik ke file JSON agar request tidak berulang
- Background worker berbasis `threading` supaya UI tetap responsif
- Auto refresh saat lagu berganti

## Catatan Penting

- Sinkronisasi paling akurat saat Chrome / Edge mengekspos playback ke `Windows Media Session`.
- Jika media session tidak tersedia, aplikasi fallback ke judul tab browser. Mode fallback tetap auto-detect lagu, tetapi sinkronisasi berjalan dengan estimasi timer dari awal deteksi lagu.
- Efek blur diaktifkan dengan pendekatan `best effort` khusus Windows 10/11. Jika blur gagal aktif di device tertentu, aplikasi tetap jalan dengan panel semi-transparan.

## Struktur Project

```text
.
├── app
│   ├── config.py
│   ├── models.py
│   ├── services
│   │   ├── browser_watcher.py
│   │   ├── cache_service.py
│   │   ├── lyrics_service.py
│   │   ├── media_session.py
│   │   └── song_normalizer.py
│   ├── ui
│   │   └── overlay_window.py
│   └── utils
│       ├── lrc_parser.py
│       └── windows_effects.py
├── data
│   └── cache
├── main.py
├── README.md
└── requirements.txt
```

## Install

Disarankan pakai Python `3.12` di Windows 10/11.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Menjalankan Aplikasi

```powershell
python main.py
```

## Cara Pakai

1. Jalankan aplikasi.
2. Buka lagu di YouTube Music atau YouTube lewat Chrome / Edge.
3. Aplikasi akan mencoba membaca metadata lagu dan mencari lirik otomatis.
4. Drag area header untuk memindahkan overlay.
5. Drag handle kanan bawah untuk resize.
6. Atur opacity via slider di header.
7. Tekan `Esc` atau tombol `×` untuk menutup aplikasi.

## Penjelasan Dependency

- `customtkinter`
  Untuk UI desktop modern dark mode.
- `tkinter`
  Bawaan Python, dipakai sebagai fondasi GUI dan canvas lyric rendering.
- `requests`
  Untuk request HTTP ke API lirik.
- `PyGetWindow`
  Fallback membaca judul window/tab browser Chrome/Edge di Windows.
- `winsdk`
  Mengakses `Windows Media Session` agar title, artist, dan posisi playback lebih akurat.
- `threading`
  Bawaan Python, dipakai untuk watcher browser dan lyric fetcher agar UI tidak freeze.

## Referensi API / Platform

- LRCLIB: https://lrclib.net
- Microsoft Global System Media Transport Controls Session Manager:
  https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager?view=winrt-28000
- PyGetWindow docs: https://pygetwindow.readthedocs.io/

