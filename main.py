import json
import math
import os
import queue
import random
import re
import socket
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, Optional, Tuple

CONFIG_PATH = "config.json"
VOTE_DURATION_SECONDS = 120


@dataclass
class ChatEvent:
    kind: str
    payload: Any


class TwitchIRCClient(threading.Thread):
    def __init__(
        self,
        channel: str,
        nickname: str,
        oauth_token: str,
        on_chat: Callable[[str, str], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        super().__init__(daemon=True)
        self.channel = channel.lower().lstrip("#")
        self.nickname = nickname
        self.oauth_token = oauth_token
        self.on_chat = on_chat
        self.on_status = on_status
        self.on_error = on_error
        self._stop_event = threading.Event()
        self.sock: Optional[socket.socket] = None

    def stop(self) -> None:
        self._stop_event.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def run(self) -> None:
        try:
            self.on_status("Connecting to Twitch IRC...")
            self.sock = socket.socket()
            self.sock.settimeout(10)
            self.sock.connect(("irc.chat.twitch.tv", 6667))
            self.sock.send(f"PASS {self.oauth_token}\r\n".encode("utf-8"))
            self.sock.send(f"NICK {self.nickname}\r\n".encode("utf-8"))
            self.sock.send(f"JOIN #{self.channel}\r\n".encode("utf-8"))
            self.sock.settimeout(1)

            self.on_status(f"Connected to #{self.channel} as {self.nickname}")
            read_buffer = ""

            while not self._stop_event.is_set():
                try:
                    data = self.sock.recv(2048)
                    if not data:
                        self.on_error("Connection closed by server.")
                        break
                    read_buffer += data.decode("utf-8", errors="ignore")
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop_event.is_set():
                        self.on_error(f"Socket error: {exc}")
                    break

                while "\r\n" in read_buffer:
                    line, read_buffer = read_buffer.split("\r\n", 1)
                    if not line:
                        continue
                    if line.startswith("PING"):
                        self.sock.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
                        continue
                    if "PRIVMSG" in line:
                        username, message = self._parse_privmsg(line)
                        if username and message:
                            self.on_chat(username, message)
        except Exception as exc:  # network/parsing hard fail
            self.on_error(f"Failed to connect/read Twitch chat: {exc}")

    @staticmethod
    def _parse_privmsg(raw_line: str) -> Tuple[str, str]:
        try:
            if "PRIVMSG" not in raw_line or "!" not in raw_line:
                return "", ""

            username = raw_line.split("!", 1)[0].lstrip(":").strip()
            parts = raw_line.split(" PRIVMSG ", 1)
            if len(parts) != 2:
                return "", ""
            tail = parts[1]
            msg_split = tail.split(" :", 1)
            if len(msg_split) != 2:
                return "", ""
            return username, msg_split[1].strip()
        except Exception:
            return "", ""


class WheelCanvas(tk.Canvas):
    COLORS = [
        "#f94144",
        "#f3722c",
        "#f8961e",
        "#f9844a",
        "#f9c74f",
        "#90be6d",
        "#43aa8b",
        "#4d908e",
        "#577590",
        "#277da1",
    ]

    def __init__(self, master: tk.Widget) -> None:
        super().__init__(master, width=700, height=700, bg="black", highlightthickness=0)
        self.rotation = 0.0
        self.entries: Dict[str, int] = {}
        self.current_phrase = ""
        self.current_voted_by = ""

    def set_entries(self, entries: Dict[str, int]) -> None:
        self.entries = {k: v for k, v in entries.items() if v > 0}
        self.draw_wheel()

    def set_rotation(self, rotation: float) -> None:
        self.rotation = rotation % 360
        self.draw_wheel()

    def set_current_info(self, phrase: str, voted_by: str) -> None:
        self.current_phrase = phrase
        self.current_voted_by = voted_by
        self.draw_wheel()

    def draw_wheel(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())

        cx = width / 2
        cy = height / 2
        pointer_margin = max(20, int(height * 0.03))
        bottom_label_margin = max(40, int(height * 0.08))
        radius = min(width * 0.45, (height - bottom_label_margin - pointer_margin) * 0.5)
        radius = max(40, radius)

        total_votes = sum(self.entries.values())
        if total_votes <= 0:
            self.create_text(
                cx,
                cy,
                text="No wheel segments yet",
                fill="white",
                font=("Arial", max(12, int(height * 0.035)), "bold"),
            )
        else:
            start_angle = self.rotation
            for idx, (phrase, votes) in enumerate(self.entries.items()):
                extent = 360.0 * (votes / total_votes)
                color = self.COLORS[idx % len(self.COLORS)]
                self.create_arc(
                    cx - radius,
                    cy - radius,
                    cx + radius,
                    cy + radius,
                    start=start_angle,
                    extent=extent,
                    fill=color,
                    outline="black",
                    width=2,
                )

                label_angle = math.radians(start_angle + extent / 2)
                tx = cx + math.cos(label_angle) * (radius * 0.6)
                ty = cy - math.sin(label_angle) * (radius * 0.6)
                self.create_text(
                    tx,
                    ty,
                    text=f"{phrase}\n({votes})",
                    fill="white",
                    font=("Arial", max(8, int(height * 0.014)), "bold"),
                    width=max(80, int(width * 0.22)),
                    justify="center",
                )
                start_angle += extent

        if self.current_phrase:
            phrase_y = height - max(52, int(height * 0.10))
            voter_y = height - max(22, int(height * 0.045))
            self.create_text(
                cx,
                phrase_y,
                text=self.current_phrase,
                fill="#00ff66",
                font=("Arial", max(15, int(height * 0.035)), "bold"),
            )
            self.create_text(
                cx,
                voter_y,
                text=self.current_voted_by,
                fill="#00ff66",
                font=("Arial", max(11, int(height * 0.024)), "bold"),
            )

        pointer_half_width = max(6, radius * 0.035)
        pointer_top = pointer_margin
        pointer_tip = pointer_top + max(12, radius * 0.09)
        self.create_polygon(
            [cx - pointer_half_width, pointer_top, cx + pointer_half_width, pointer_top, cx, pointer_tip],
            fill="white",
            outline="white",
        )


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Twitch Vote Wheel Controller")
        self.root.geometry("1000x760")

        self.config = self.load_config()
        self.event_queue: "queue.Queue[ChatEvent]" = queue.Queue()

        self.voting_active = False
        self.vote_end_at = 0.0
        self.spinning = False
        self.rotation = 0.0
        self.spin_velocity = 0.0
        self.vote_counts: Dict[str, int] = {}
        self.user_votes: Dict[str, str] = {}

        self.irc_client: Optional[TwitchIRCClient] = None

        self._build_main_window()
        self._build_wheel_window()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.process_events)
        self.root.after(250, self.update_timer)
        self.root.after(16, self.update_spin_state)

        self.connect_chat()

    def load_config(self) -> dict:
        if not os.path.exists(CONFIG_PATH):
            default = {
                "channel": "itskxtlyn",
                "nickname": "your_bot_username",
                "oauth_token": "oauth:your_token_here",
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_main_window(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Top phrases on wheel:").grid(row=0, column=0, sticky="w")
        self.max_phrases_var = tk.StringVar(value="10")
        self.max_phrases_var.trace_add("write", self.on_top_phrases_changed)
        ttk.Entry(top, textvariable=self.max_phrases_var, width=8).grid(row=0, column=1, padx=4)

        self.start_btn = ttk.Button(top, text="startvote", command=self.start_vote)
        self.start_btn.grid(row=0, column=2, padx=5)

        ttk.Button(top, text="stopvote", command=self.stop_vote).grid(row=0, column=3, padx=5)

        ttk.Button(top, text="clearvote", command=self.clear_vote).grid(row=0, column=4, padx=5)
        ttk.Button(top, text="spinwheel", command=self.spin_wheel).grid(row=0, column=5, padx=5)

        self.timer_var = tk.StringVar(value="Voting idle")
        ttk.Label(top, textvariable=self.timer_var, font=("Arial", 11, "bold")).grid(row=0, column=6, padx=10, sticky="w")

        status_frame = ttk.Frame(self.root, padding=10)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, text="Status:").pack(side="left")
        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(status_frame, textvariable=self.status_var, foreground="blue").pack(side="left", padx=6)

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        table_frame = ttk.Labelframe(main, text="Wheel Segments", padding=8)
        chat_frame = ttk.Labelframe(main, text="Live Chat Feed", padding=8)
        main.add(table_frame, weight=2)
        main.add(chat_frame, weight=2)

        io_controls = ttk.Frame(table_frame)
        io_controls.pack(fill="x", pady=(0, 6))
        ttk.Button(io_controls, text="Import Segments", command=self.import_segments).pack(side="left")
        ttk.Button(io_controls, text="Export Segments", command=self.export_segments).pack(side="left", padx=6)

        tree_container = ttk.Frame(table_frame)
        tree_container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_container, columns=("phrase", "votes"), show="headings", height=20)
        self.tree.heading("phrase", text="Phrase")
        self.tree.heading("votes", text="Votes")
        self.tree.column("phrase", width=230)
        self.tree.column("votes", width=80, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        tree_scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        self.tree.bind("<Double-1>", self.edit_tree_cell)

        control = ttk.Frame(table_frame)
        control.pack(fill="x", pady=(6, 0))
        self.new_phrase = tk.StringVar()
        self.new_votes = tk.StringVar(value="1")
        ttk.Entry(control, textvariable=self.new_phrase).pack(side="left", fill="x", expand=True)
        ttk.Entry(control, textvariable=self.new_votes, width=6).pack(side="left", padx=4)
        ttk.Button(control, text="Add/Update", command=self.add_or_update_segment).pack(side="left", padx=4)
        ttk.Button(control, text="Remove Selected", command=self.remove_selected).pack(side="left")

        self.chat_text = tk.Text(chat_frame, wrap="word", state="disabled", bg="#121212", fg="#d8f8d8", height=20)
        self.chat_text.pack(fill="both", expand=True)

    def _build_wheel_window(self) -> None:
        self.wheel_window = tk.Toplevel(self.root)
        self.wheel_window.title("Twitch Vote Wheel")
        self.wheel_window.geometry("720x720")
        self.wheel_window.minsize(360, 360)
        self.wheel_window.aspect(1, 1, 1, 1)

        self.wheel_canvas = WheelCanvas(self.wheel_window)
        self.wheel_canvas.pack(fill="both", expand=True)
        self.wheel_canvas.bind("<Configure>", lambda _e: self.wheel_canvas.draw_wheel())

    def connect_chat(self) -> None:
        channel = self.config.get("channel", "itskxtlyn")
        nickname = self.config.get("nickname", "")
        token = self.config.get("oauth_token", "")

        if not nickname or not token or "your_token_here" in token:
            self.set_status("Config missing nickname/oauth_token. Update config.json.", error=True)
            return

        self.irc_client = TwitchIRCClient(
            channel=channel,
            nickname=nickname,
            oauth_token=token,
            on_chat=lambda u, m: self.event_queue.put(ChatEvent("chat", (u, m))),
            on_status=lambda s: self.event_queue.put(ChatEvent("status", s)),
            on_error=lambda e: self.event_queue.put(ChatEvent("error", e)),
        )
        self.irc_client.start()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)

    def log_chat(self, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", text + "\n")
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def process_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event.kind == "chat":
                username, message = event.payload
                self.log_chat(f"[{username}] {message}")
                self.consume_vote(username, message)
            elif event.kind == "status":
                self.set_status(event.payload)
            elif event.kind == "error":
                self.set_status(event.payload, error=True)
                self.log_chat(f"[ERROR] {event.payload}")

        self.root.after(100, self.process_events)

    @staticmethod
    def normalize_phrase(text: str) -> str:
        lowered = " ".join(text.strip().lower().split())
        return re.sub(r"[^a-z0-9\s]", "", lowered).strip()

    def find_matching_phrase(self, phrase: str, ignore_phrase: str = "") -> Optional[str]:
        if not phrase:
            return None

        for existing in self.vote_counts:
            if ignore_phrase and existing == ignore_phrase:
                continue

            if phrase == existing:
                return existing

            if phrase in existing or existing in phrase:
                return existing

            ratio = SequenceMatcher(None, phrase, existing).ratio()
            if ratio >= 0.86:
                return existing

        return None

    def consume_vote(self, username: str, message: str) -> None:
        if not self.voting_active:
            return

        username = username.strip().lower()
        if not username:
            return

        phrase = self.normalize_phrase(message)
        if not phrase:
            return

        matched_phrase = self.find_matching_phrase(phrase)
        target_phrase = matched_phrase or phrase

        previous_phrase = self.user_votes.get(username)
        if previous_phrase == target_phrase:
            return

        if previous_phrase:
            if previous_phrase in self.vote_counts:
                self.vote_counts[previous_phrase] -= 1
                if self.vote_counts[previous_phrase] <= 0:
                    self.vote_counts.pop(previous_phrase, None)

        self.vote_counts[target_phrase] = self.vote_counts.get(target_phrase, 0) + 1
        self.user_votes[username] = target_phrase
        self.refresh_table_from_votes()

    def get_top_votes(self) -> Dict[str, int]:
        max_phrases = max(1, self.safe_int(self.max_phrases_var.get(), 10))
        return dict(sorted(self.vote_counts.items(), key=lambda x: (-x[1], x[0]))[:max_phrases])

    def on_top_phrases_changed(self, *_args: Any) -> None:
        self.refresh_table_from_votes()

    def pointer_details(self) -> Tuple[str, str]:
        top_votes = self.get_top_votes()
        total = sum(top_votes.values())
        if total <= 0:
            return "", ""

        pointer_angle = 90.0
        wheel_angle = (pointer_angle - (self.rotation % 360)) % 360

        running = 0.0
        for phrase, votes in top_votes.items():
            extent = 360.0 * (votes / total)
            if running <= wheel_angle < running + extent:
                phrase_users = sorted(username for username, user_phrase in self.user_votes.items() if user_phrase == phrase)
                voter_slots = phrase_users[:votes]
                if len(voter_slots) < votes:
                    missing = votes - len(voter_slots)
                    voter_slots.extend([f"unknown-{i + 1}" for i in range(missing)])

                if not voter_slots:
                    return phrase, "voted by: -"

                local_angle = wheel_angle - running
                slot_extent = extent / len(voter_slots)
                slot_idx = min(len(voter_slots) - 1, int(local_angle / slot_extent))
                return phrase, f"voted by: {voter_slots[slot_idx]}"
            running += extent

        fallback_phrase = next(iter(top_votes), "")
        return fallback_phrase, "voted by: -"

    def refresh_table_from_votes(self) -> None:
        top_votes = self.get_top_votes()
        all_votes = dict(sorted(self.vote_counts.items(), key=lambda x: (-x[1], x[0])))

        self.tree.delete(*self.tree.get_children())
        for phrase, votes in all_votes.items():
            self.tree.insert("", "end", values=(phrase, votes))
        self.wheel_canvas.set_entries(top_votes)
        current_phrase, current_voter = self.pointer_details()
        self.wheel_canvas.set_current_info(current_phrase, current_voter)

    def start_vote(self) -> None:
        self.voting_active = True
        self.vote_end_at = time.time() + VOTE_DURATION_SECONDS
        self.timer_var.set("Voting active: 120s")

    def clear_vote(self) -> None:
        self.voting_active = False
        self.vote_end_at = 0
        self.vote_counts.clear()
        self.user_votes.clear()
        self.refresh_table_from_votes()
        self.timer_var.set("Voting idle")

    def stop_vote(self) -> None:
        if not self.voting_active:
            return
        self.voting_active = False
        self.vote_end_at = 0
        self.timer_var.set("Voting stopped early")

    def update_timer(self) -> None:
        if self.voting_active:
            remaining = max(0, int(self.vote_end_at - time.time()))
            self.timer_var.set(f"Voting active: {remaining}s")
            if remaining <= 0:
                self.voting_active = False
                self.timer_var.set("Voting ended")
        self.root.after(250, self.update_timer)

    def add_or_update_segment(self) -> None:
        phrase = self.normalize_phrase(self.new_phrase.get())
        votes = self.safe_int(self.new_votes.get(), 1)
        if not phrase:
            return

        matched_phrase = self.find_matching_phrase(phrase)
        if matched_phrase and matched_phrase != phrase:
            self.vote_counts[matched_phrase] = max(0, self.vote_counts.get(matched_phrase, 0) + votes)
            target_phrase = matched_phrase
        else:
            self.vote_counts[phrase] = max(0, votes)
            target_phrase = phrase

        if self.vote_counts.get(target_phrase, 0) <= 0:
            self.vote_counts.pop(target_phrase, None)
        self.refresh_table_from_votes()
        self.new_phrase.set("")

    def remove_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        for item in selection:
            phrase = self.tree.item(item, "values")[0]
            self.vote_counts.pop(phrase, None)
        self.refresh_table_from_votes()

    def export_segments(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export Wheel Segments",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        top_votes = self.get_top_votes()
        top_phrases = set(top_votes.keys())

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# TWITCH_WHEEL_EXPORT_V2\n")
                for phrase, votes in sorted(top_votes.items(), key=lambda x: (-x[1], x[0])):
                    f.write(f"SEGMENT\t{phrase}\t{votes}\n")

                for username, phrase in sorted(self.user_votes.items()):
                    if phrase in top_phrases:
                        f.write(f"USERVOTE\t{username}\t{phrase}\n")

            self.set_status(f"Exported {len(top_votes)} segments (+ user votes) to {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror("Export failed", f"Could not export segments:\n{exc}")

    def import_segments(self) -> None:
        path = filedialog.askopenfilename(
            title="Import Wheel Segments",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        imported: Dict[str, int] = {}
        imported_user_votes: Dict[str, str] = {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split("\t")

                    if len(parts) >= 3 and parts[0] == "SEGMENT":
                        phrase = self.normalize_phrase(parts[1])
                        votes = self.safe_int(parts[2].strip(), 0)
                        if phrase and votes > 0:
                            existing = self.find_matching_phrase(phrase)
                            target = existing or phrase
                            imported[target] = imported.get(target, 0) + votes
                        continue

                    if len(parts) >= 3 and parts[0] == "USERVOTE":
                        username = parts[1].strip().lower()
                        phrase = self.normalize_phrase(parts[2])
                        if username and phrase:
                            imported_user_votes[username] = phrase
                        continue

                    if "	" in line:
                        phrase_raw, votes_raw = line.rsplit("	", 1)
                    else:
                        legacy = line.rsplit(" ", 1)
                        if len(legacy) != 2:
                            continue
                        phrase_raw, votes_raw = legacy

                    phrase = self.normalize_phrase(phrase_raw)
                    votes = self.safe_int(votes_raw.strip(), 0)
                    if not phrase or votes <= 0:
                        continue

                    existing = self.find_matching_phrase(phrase)
                    target = existing or phrase
                    imported[target] = imported.get(target, 0) + votes

            self.vote_counts = imported
            self.user_votes = {
                username: phrase
                for username, phrase in imported_user_votes.items()
                if phrase in self.vote_counts and self.vote_counts.get(phrase, 0) > 0
            }

            for phrase in self.user_votes.values():
                if phrase not in self.vote_counts:
                    self.vote_counts[phrase] = 1

            self.refresh_table_from_votes()
            self.set_status(
                f"Imported {len(imported)} segments and {len(self.user_votes)} user votes from {os.path.basename(path)}"
            )
        except OSError as exc:
            messagebox.showerror("Import failed", f"Could not import segments:\n{exc}")

    def edit_tree_cell(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item_id or col not in ("#1", "#2"):
            return

        x, y, w, h = self.tree.bbox(item_id, col)
        current = self.tree.set(item_id, col)
        editor = ttk.Entry(self.tree)
        editor.place(x=x, y=y, width=w, height=h)
        editor.insert(0, current)
        editor.focus_set()

        def save_edit(_: Optional[tk.Event] = None) -> None:
            new_value = editor.get().strip()
            phrase_old = self.tree.set(item_id, "phrase")
            votes_old = self.safe_int(self.tree.set(item_id, "votes"), 1)
            editor.destroy()

            if col == "#1":
                phrase_new = self.normalize_phrase(new_value)
                if not phrase_new:
                    return
                if phrase_new != phrase_old:
                    self.vote_counts.pop(phrase_old, None)
                    matched_phrase = self.find_matching_phrase(phrase_new, ignore_phrase=phrase_old)
                    target_phrase = matched_phrase or phrase_new
                    self.vote_counts[target_phrase] = self.vote_counts.get(target_phrase, 0) + votes_old
            elif col == "#2":
                votes_new = self.safe_int(new_value, votes_old)
                if phrase_old in self.vote_counts:
                    if votes_new <= 0:
                        self.vote_counts.pop(phrase_old, None)
                    else:
                        self.vote_counts[phrase_old] = votes_new

            self.refresh_table_from_votes()

        editor.bind("<Return>", save_edit)
        editor.bind("<FocusOut>", save_edit)

    def spin_wheel(self) -> None:
        top_votes = self.get_top_votes()
        if not any(v > 0 for v in top_votes.values()):
            messagebox.showinfo("No segments", "Add at least one phrase with votes before spinning.")
            return

        self.spin_velocity += random.uniform(18, 28)
        self.spin_velocity = min(self.spin_velocity, 120.0)
        self.spinning = True

    def update_spin_state(self) -> None:
        if self.spinning or self.spin_velocity > 0:
            self.rotation += self.spin_velocity
            self.spin_velocity *= 0.985

            if self.spin_velocity < 0.05:
                self.spin_velocity = 0.0
                self.spinning = False

            self.wheel_canvas.set_rotation(self.rotation)

        current_phrase, current_voter = self.pointer_details()
        self.wheel_canvas.set_current_info(current_phrase, current_voter)

        self.root.after(16, self.update_spin_state)

    @staticmethod
    def safe_int(text: str, default: int) -> int:
        try:
            return int(text)
        except (TypeError, ValueError):
            return default

    def on_close(self) -> None:
        if self.irc_client:
            self.irc_client.stop()
        self.root.destroy()


if __name__ == "__main__":
    app_root = tk.Tk()
    App(app_root)
    app_root.mainloop()
