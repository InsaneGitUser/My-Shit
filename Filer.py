import os
import sys
import xml.etree.ElementTree as ET
import http.server
import socketserver
import threading
import socket
import re as _re
import mimetypes
import tkinter as tk
from tkinter import filedialog
from datetime import datetime

PORT = 1111
server_instance = None
server_thread    = None
generated_xml    = None
base_dir         = None

# ── XML ──────────────────────────────────────────────────────────────────────

def detect_type(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in [".mp4", ".mkv", ".mov", ".webm"]: return "video"
    if ext in [".mp3", ".wav", ".ogg"]:           return "audio"
    if ext in [".png", ".jpg", ".jpeg", ".gif"]:  return "image"
    if ext in [".txt", ".md"]:                    return "text"
    return "file"

def build_tree(path, xml_parent):
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return
    for item in entries:
        if item == "index.xml":
            continue
        full = os.path.join(path, item)
        if os.path.isdir(full):
            build_tree(full, ET.SubElement(xml_parent, "folder", name=item))
        else:
            ET.SubElement(xml_parent, "file", name=item, type=detect_type(item))

def generate_xml(base):
    root = ET.Element("files")
    build_tree(base, root)
    xml_path = os.path.join(base, "index.xml")
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path

def delete_xml():
    global generated_xml
    if generated_xml and os.path.exists(generated_xml):
        os.remove(generated_xml)
        generated_xml = None

# ── HTTP handler with range support ──────────────────────────────────────────

def make_handler(log_callback):
    class LoggingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self._resolve_path()
            if path is None:
                self.send_error(404)
                return
            if os.path.isdir(path):
                # serve index.xml directly if requested
                self.send_error(403)
                return
            self._serve_file(path)

        def _resolve_path(self):
            # strip query string
            url_path = self.path.split("?")[0]
            # url decode
            import urllib.parse
            url_path = urllib.parse.unquote(url_path)
            # map to filesystem
            full = os.path.join(base_dir, url_path.lstrip("/"))
            full = os.path.normpath(full)
            # security: ensure it's inside base_dir
            if not full.startswith(os.path.normpath(base_dir)):
                return None
            if os.path.isfile(full):
                return full
            return None

        def _serve_file(self, path):
            file_size = os.path.getsize(path)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            range_header = self.headers.get("Range")

            if range_header:
                m = _re.search("([0-9]+)-([0-9]*)", range_header)
                if m:
                    byte1 = int(m.group(1))
                    byte2 = int(m.group(2)) if m.group(2) else file_size - 1
                    byte2 = min(byte2, file_size - 1)
                    length = byte2 - byte1 + 1
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {byte1}-{byte2}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.end_headers()
                    with open(path, "rb") as f:
                        f.seek(byte1)
                        remaining = length
                        while remaining > 0:
                            data = f.read(min(65536, remaining))
                            if not data:
                                break
                            self.wfile.write(data)
                            remaining -= len(data)
                    return

            # full file
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    self.wfile.write(data)

        def log_message(self, format, *args):
            client_ip = self.client_address[0]
            path      = self.path
            ts        = datetime.now().strftime("%H:%M:%S")
            if "index.xml" in path:
                log_callback(f"[{ts}]  📺  {client_ip}  connected")
            else:
                fname = path.split("/")[-1] or path
                log_callback(f"[{ts}]  📂  {client_ip}  → {fname}")

        def log_error(self, format, *args):
            pass

    return LoggingHandler

# ── Server start/stop ────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_server(directory, log_callback, status_callback):
    global server_instance, server_thread, generated_xml, base_dir
    base_dir = os.path.abspath(directory)
    if not os.path.isdir(base_dir):
        status_callback("error", "Directory not found.")
        return
    generated_xml = generate_xml(base_dir)
    handler = make_handler(log_callback)
    try:
        socketserver.TCPServer.allow_reuse_address = True
        server_instance = socketserver.ThreadingTCPServer(("", PORT), handler)
    except OSError as e:
        status_callback("error", f"Port {PORT} in use: {e}")
        delete_xml()
        return
    server_thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
    server_thread.start()
    local_ip = get_local_ip()
    status_callback("running", f"{local_ip}:{PORT}")
    log_callback(f"[{datetime.now().strftime('%H:%M:%S')}]  ✅  Server started — {base_dir}")

def stop_server(log_callback, status_callback):
    global server_instance
    if server_instance:
        server_instance.shutdown()
        server_instance = None
    delete_xml()
    status_callback("stopped", "")
    log_callback(f"[{datetime.now().strftime('%H:%M:%S')}]  🛑  Server stopped")

# ── GUI ──────────────────────────────────────────────────────────────────────

BG       = "#0e0e0e"
SURFACE  = "#1a1a1a"
BORDER   = "#2a2a2a"
ACCENT   = "#e8e8e8"
DIM      = "#555555"
GREEN    = "#39d98a"
RED      = "#ff4d4d"
AMBER    = "#f5a623"
FONT_UI  = ("Courier New", 11)
FONT_LOG = ("Courier New", 10)
FONT_BIG = ("Courier New", 22, "bold")

class FilerServer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Filer Server")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.geometry("720x540")
        self._running = False
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=32, pady=(28, 0))
        tk.Label(hdr, text="FILER", font=FONT_BIG, bg=BG, fg=ACCENT).pack(side="left")
        self.dot = tk.Label(hdr, text="●", font=("Courier New", 14), bg=BG, fg=DIM)
        self.dot.pack(side="left", padx=(12, 4), pady=(6, 0))
        self.status_lbl = tk.Label(hdr, text="offline", font=FONT_UI, bg=BG, fg=DIM)
        self.status_lbl.pack(side="left", pady=(6, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=32, pady=16)

        dir_frame = tk.Frame(self, bg=BG)
        dir_frame.pack(fill="x", padx=32)
        tk.Label(dir_frame, text="DIRECTORY", font=("Courier New", 9), bg=BG, fg=DIM).pack(anchor="w")
        row = tk.Frame(dir_frame, bg=BG)
        row.pack(fill="x", pady=(4, 0))
        self.dir_var = tk.StringVar()
        self.dir_entry = tk.Entry(row, textvariable=self.dir_var, font=FONT_UI, bg=SURFACE, fg=ACCENT,
            insertbackground=ACCENT, relief="flat", bd=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT)
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        tk.Button(row, text="BROWSE", font=("Courier New", 9, "bold"), bg=SURFACE, fg=DIM,
            activebackground=BORDER, activeforeground=ACCENT, relief="flat", bd=0, cursor="hand2",
            highlightthickness=1, highlightbackground=BORDER, padx=12, pady=8,
            command=self._browse).pack(side="left")

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill="x", padx=32, pady=16)
        self.action_btn = tk.Button(btn_frame, text="START SERVER", font=("Courier New", 11, "bold"),
            bg=GREEN, fg="#000000", activebackground="#2ebd76", activeforeground="#000000",
            relief="flat", bd=0, cursor="hand2", padx=24, pady=10, command=self._toggle)
        self.action_btn.pack(side="left")
        self.ip_lbl = tk.Label(btn_frame, text="", font=FONT_UI, bg=BG, fg=DIM)
        self.ip_lbl.pack(side="left", padx=20)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=32, pady=(0, 12))
        tk.Label(self, text="ACTIVITY LOG", font=("Courier New", 9), bg=BG, fg=DIM).pack(anchor="w", padx=32)

        log_frame = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        log_frame.pack(fill="both", expand=True, padx=32, pady=(6, 28))
        self.log_box = tk.Text(log_frame, font=FONT_LOG, bg=SURFACE, fg="#888888",
            relief="flat", bd=0, state="disabled", cursor="arrow", wrap="word", padx=12, pady=10)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("connected", foreground=GREEN)
        self.log_box.tag_config("file",      foreground="#6699cc")
        self.log_box.tag_config("system",    foreground=AMBER)
        self.log_box.tag_config("error",     foreground=RED)

    def _browse(self):
        d = filedialog.askdirectory()
        if d:
            self.dir_var.set(d)

    def _toggle(self):
        if not self._running:
            d = self.dir_var.get().strip()
            if not d:
                self._log("  No directory selected.", "error")
                return
            start_server(d, self._log, self._set_status)
        else:
            stop_server(self._log, self._set_status)

    def _set_status(self, state, message):
        if state == "running":
            self._running = True
            self.dot.config(fg=GREEN)
            self.status_lbl.config(fg=GREEN, text="running")
            self.action_btn.config(text="STOP SERVER", bg=RED, activebackground="#cc3333", fg="#ffffff")
            self.ip_lbl.config(text=message, fg=DIM)
            self.dir_entry.config(state="disabled")
        elif state == "stopped":
            self._running = False
            self.dot.config(fg=DIM)
            self.status_lbl.config(fg=DIM, text="offline")
            self.action_btn.config(text="START SERVER", bg=GREEN, activebackground="#2ebd76", fg="#000000")
            self.ip_lbl.config(text="")
            self.dir_entry.config(state="normal")
        elif state == "error":
            self._running = False
            self.dot.config(fg=RED)
            self.status_lbl.config(fg=RED, text="error")
            self._log(f"  {message}", "error")

    def _log(self, message, tag=None):
        if tag is None:
            if "📺" in message or "✅" in message:
                tag = "system"
            elif "📂" in message:
                tag = "file"
            elif "🛑" in message:
                tag = "system"
            else:
                tag = "system"
        def _insert():
            self.log_box.config(state="normal")
            self.log_box.insert("end", message + "\n", tag)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _insert)

    def destroy(self):
        if self._running:
            stop_server(lambda m: None, lambda s, m: None)
        super().destroy()

if __name__ == "__main__":
    app = FilerServer()
    app.mainloop()
