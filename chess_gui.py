#!/usr/bin/env python3

import chess
import chess.engine
import time
import random
import threading
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import os
import sys
import winsound


STOCKFISH_PATH = r"C:\Users\ismai\Desktop\chess-simulator\stockfish\stockfish-windows-x86-64-avx2.exe"
STOCKFISH_ELO  = 1800

TIME_CONTROL = {
    "base_time": 3600,
    "increment": 15,
}

MULTIPV       = 3
ANALYSIS_TIME = 0.5
T_BASE        = 20
T_COEFF       = 45
T_MIN         = 3
T_MAX         = 600

# ─────────────────────────────────────────────
#  Pièces Unicode
# ─────────────────────────────────────────────

PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

LIGHT_SQ = "#F0D9B5"
DARK_SQ  = "#B58863"
SEL_CLR  = "#7FC97F"
LEGAL_CLR = "#AAD8AA"
LAST_CLR = "#CDD16E"
CHECK_CLR = "#FF6B6B"

SQ_SIZE = 72

def score_phase(board):
    move_num = board.fullmove_number
    major = (len(board.pieces(chess.QUEEN, chess.WHITE))
           + len(board.pieces(chess.QUEEN, chess.BLACK))
           + len(board.pieces(chess.ROOK,  chess.WHITE))
           + len(board.pieces(chess.ROOK,  chess.BLACK)))
    if move_num <= 10:  return 1.0
    elif major >= 4:    return 3.0
    else:               return 4.0

def score_tactical(board):
    legal = list(board.legal_moves)
    captures = sum(1 for m in legal if board.is_capture(m))
    checks    = sum(1 for m in legal if board.gives_check(m))
    return min(captures * 0.4 + checks * 0.6, 5.0)

def score_criticality(prev, curr):
    if prev is None or curr is None: return 0.0
    return min(abs(curr - prev) / 50, 8.0)

def score_difficulty(infos):
    if len(infos) < 2: return 0.0
    scores = []
    for info in infos:
        s = info.get("score")
        if s and not s.is_mate():
            scores.append(s.relative.score())
    if len(scores) < 2: return 0.0
    gap = abs(scores[0] - scores[1]) / 100.0
    if gap < 0.1:   return 4.0
    elif gap < 0.3: return 3.0
    elif gap < 0.7: return 2.0
    elif gap < 1.5: return 1.0
    else:           return 0.0

def score_clock_pressure(remaining):
    if remaining > 1800: return  0.0
    elif remaining > 600: return -1.5
    elif remaining > 300: return -2.5
    else:                 return -3.0

def score_position_state(curr):
    if curr is None: return 0.0
    if curr > 150:   return 1.5
    elif curr < -150: return 3.0
    else:             return 0.0

def compute_think_time(board, infos, prev_eval, curr_eval, remaining):
    s = (score_phase(board)
       + score_tactical(board)    * 2
       + score_criticality(prev_eval, curr_eval) * 3
       + score_difficulty(infos)  * 2
       + score_clock_pressure(remaining)
       + score_position_state(curr_eval))
    s = max(0.0, s)
    mn = board.fullmove_number
    t  = T_BASE + T_COEFF * s
    if mn <= 10:   t = min(t, 45);  noise = random.uniform(2, 15)
    elif mn <= 25: t = min(t, 180); noise = random.uniform(5, 40)
    else:          noise = random.uniform(10, 60)
    if random.random() < 0.4: noise = -noise
    t = max(T_MIN, min(T_MAX, t + noise))
    return min(t, remaining * 0.25)

class ChessApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simulateur OTB — Stockfish × Pendule")
        self.resizable(False, False)
        self.configure(bg="#1E1E1E")

        self.board      = chess.Board()
        self.engine     = None
        self.player_color = chess.WHITE
        self.clocks     = {chess.WHITE: float(TIME_CONTROL["base_time"]),
                           chess.BLACK: float(TIME_CONTROL["base_time"])}
        self.increment  = float(TIME_CONTROL["increment"])
        self.active_clock = None
        self.clock_start  = None
        self.game_over    = False
        self.waiting_player = False
        self.engine_thinking = False

        self.selected_sq  = None
        self.legal_targets = []
        self.last_move    = None
        self.prev_eval    = None

        self._build_ui()
        self._load_engine()
        self._show_setup()

    
    def _build_ui(self):
        self.main_frame = tk.Frame(self, bg="#1E1E1E")
        self.main_frame.pack(padx=16, pady=16)
        left = tk.Frame(self.main_frame, bg="#1E1E1E")
        left.grid(row=0, column=0, padx=(0, 16))
        self.canvas = tk.Canvas(left,
            width=SQ_SIZE * 8 + 24,
            height=SQ_SIZE * 8 + 24,
            bg="#1E1E1E", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_board_click)
        right = tk.Frame(self.main_frame, bg="#1E1E1E", width=280)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_propagate(False)
        self.engine_frame = self._clock_widget(right, "Stockfish", "#B58863")
        self.engine_frame.pack(fill="x", pady=(0, 8))
        eval_f = tk.Frame(right, bg="#2A2A2A", relief="flat")
        eval_f.pack(fill="x", pady=(0, 8))
        tk.Label(eval_f, text="Évaluation", bg="#2A2A2A", fg="#888",
                 font=("Helvetica", 10)).pack(anchor="w", padx=10, pady=(6,0))
        self.eval_bar_frame = tk.Frame(eval_f, bg="#333", height=8)
        self.eval_bar_frame.pack(fill="x", padx=10, pady=4)
        self.eval_bar = tk.Frame(self.eval_bar_frame, bg="#888", height=8)
        self.eval_bar.place(x=0, y=0, relwidth=0.5, relheight=1.0)
        self.eval_label = tk.Label(eval_f, text="0.00", bg="#2A2A2A", fg="#AAA",
                                   font=("Helvetica", 10))
        self.eval_label.pack(anchor="w", padx=10, pady=(0,6))
        self.player_frame = self._clock_widget(right, "Vous (Blancs)", "#F0D9B5")
        self.player_frame.pack(fill="x", pady=(0, 12))
        input_f = tk.Frame(right, bg="#2A2A2A", relief="flat")
        input_f.pack(fill="x", pady=(0, 8))
        tk.Label(input_f, text="Votre coup (SAN ou UCI)", bg="#2A2A2A", fg="#888",
                 font=("Helvetica", 10)).pack(anchor="w", padx=10, pady=(8,2))
        row = tk.Frame(input_f, bg="#2A2A2A")
        row.pack(fill="x", padx=10, pady=(0, 8))
        self.move_var = tk.StringVar()
        self.move_entry = tk.Entry(row, textvariable=self.move_var,
            font=("Courier", 14), bg="#333", fg="#EEE",
            insertbackground="#EEE", relief="flat",
            highlightthickness=1, highlightcolor="#555",
            highlightbackground="#444", width=10)
        self.move_entry.pack(side="left", ipady=5, padx=(0,6))
        self.move_entry.bind("<Return>", lambda e: self._play_text_move())
        self.play_btn = tk.Button(row, text="Jouer", command=self._play_text_move,
            bg="#4A7C59", fg="white", font=("Helvetica", 11, "bold"),
            relief="flat", padx=12, pady=5, cursor="hand2",
            activebackground="#3A6A49", activeforeground="white",
            disabledforeground="#666")
        self.play_btn.pack(side="left")
        btn_row = tk.Frame(right, bg="#1E1E1E")
        btn_row.pack(fill="x", pady=(0,8))
        for txt, cmd, clr in [
            ("Abandon",  self._abandon, "#8B3333"),
            ("Nulle",    self._draw,    "#555"),
            ("Nouvelle", self._new_game,"#335577"),
        ]:
            tk.Button(btn_row, text=txt, command=cmd,
                bg=clr, fg="white", font=("Helvetica", 10),
                relief="flat", padx=8, pady=4, cursor="hand2",
                activebackground=clr, activeforeground="white"
            ).pack(side="left", padx=3)
        self.status_var = tk.StringVar(value="")
        self.status_lbl = tk.Label(right, textvariable=self.status_var,
            bg="#1E1E1E", fg="#CCC", font=("Helvetica", 10),
            wraplength=270, justify="left")
        self.status_lbl.pack(anchor="w", pady=(0,8))
        hist_f = tk.Frame(right, bg="#2A2A2A")
        hist_f.pack(fill="both", expand=True)
        tk.Label(hist_f, text="Coups joués", bg="#2A2A2A", fg="#888",
                 font=("Helvetica", 10)).pack(anchor="w", padx=10, pady=(6,2))
        self.hist_text = tk.Text(hist_f, bg="#2A2A2A", fg="#CCC",
            font=("Courier", 11), relief="flat", state="disabled",
            height=8, width=32, wrap="word")
        self.hist_text.pack(padx=10, pady=(0,8), fill="both", expand=True)
        self.fen_var = tk.StringVar()
        tk.Label(right, textvariable=self.fen_var, bg="#1E1E1E", fg="#555",
                 font=("Courier", 8), wraplength=270).pack(anchor="w")
        self.setup_win = None
    def _clock_widget(self, parent, label, accent):
        f = tk.Frame(parent, bg="#2A2A2A", relief="flat")
        tk.Label(f, text=label, bg="#2A2A2A", fg=accent,
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=12, pady=(8,0))
        time_lbl = tk.Label(f, text="1:00:00", bg="#2A2A2A", fg="#EEEEEE",
                             font=("Courier", 30, "bold"))
        time_lbl.pack(anchor="w", padx=12, pady=(0,8))
        f._time_label = time_lbl
        f._label      = label
        return f
    def _show_setup(self):
        win = tk.Toplevel(self)
        win.title("Nouvelle partie")
        win.configure(bg="#1E1E1E")
        win.resizable(False, False)
        win.grab_set()
        self.setup_win = win
        pad = {"padx": 20, "pady": 6}
        tk.Label(win, text="♟  Simulateur OTB", bg="#1E1E1E", fg="#F0D9B5",
                 font=("Helvetica", 16, "bold")).pack(padx=20, pady=(20,4))
        tk.Label(win, text="Vous jouez :", bg="#1E1E1E", fg="#AAA",
                 font=("Helvetica", 11)).pack(**pad)
        self.color_var = tk.StringVar(value="w")
        cf = tk.Frame(win, bg="#1E1E1E")
        cf.pack()
        for txt, val in [("Blancs ♔", "w"), ("Noirs ♚", "b")]:
            tk.Radiobutton(cf, text=txt, variable=self.color_var, value=val,
                bg="#1E1E1E", fg="#EEE", selectcolor="#333",
                activebackground="#1E1E1E", font=("Helvetica", 11),
                cursor="hand2").pack(side="left", padx=12)
        tk.Label(win, text="Cadence :", bg="#1E1E1E", fg="#AAA",
                 font=("Helvetica", 11)).pack(**pad)
        self.tc_var = tk.StringVar(value="3600,15")
        for txt, val in [
            ("60 min + 15s", "3600,15"),
            ("90 min + 30s", "5400,30"),
            ("2h + 0s",      "7200,0"),
            ("30 min + 10s", "1800,10"),
            ("40 min + 20min/40 + 0s", "2400,0,40,1200,10"),
        ]:
            tk.Radiobutton(win, text=txt, variable=self.tc_var, value=val,
                bg="#1E1E1E", fg="#EEE", selectcolor="#333",
                activebackground="#1E1E1E", font=("Helvetica", 11),
                cursor="hand2").pack(anchor="w", padx=30)
        tk.Label(win, text="Niveau Stockfish :", bg="#1E1E1E", fg="#AAA",
                 font=("Helvetica", 11)).pack(**pad)
        self.elo_var = tk.IntVar(value=1800)
        elo_frame = tk.Frame(win, bg="#1E1E1E")
        elo_frame.pack(**pad)
        self.elo_lbl = tk.Label(elo_frame, text="1800", bg="#1E1E1E", fg="#F0D9B5",
                                font=("Courier", 13, "bold"), width=5)
        self.elo_lbl.pack(side="right", padx=8)
        elo_sl = tk.Scale(elo_frame, from_=800, to=2800, orient="horizontal",
            variable=self.elo_var, bg="#1E1E1E", fg="#AAA",
            troughcolor="#333", highlightthickness=0, length=200,
            showvalue=False, command=lambda v: self.elo_lbl.config(text=v))
        elo_sl.pack(side="left")

        tk.Button(win, text="Démarrer la partie", command=self._start_game,
            bg="#4A7C59", fg="white", font=("Helvetica", 13, "bold"),
            relief="flat", padx=20, pady=10, cursor="hand2",
            activebackground="#3A6A49"
        ).pack(pady=(16, 20))
    def _start_game(self):
        if self.setup_win:
            self.setup_win.destroy()
            self.setup_win = None
        tc = self.tc_var.get().split(",")
        base = float(tc[0])
        self.increment = float(tc[1])
        self.bonus_move = int(tc[2]) if len(tc) > 2 else None
        self.bonus_time = float(tc[3]) if len(tc) > 3 else 0 
        self.bonus_increment_after_bonus = float(tc[4]) if len(tc) > 4 else self.increment
        self.player_color = chess.WHITE if self.color_var.get() == "w" else chess.BLACK
        STOCKFISH_ELO_live = self.elo_var.get()
        self.board = chess.Board()
        self.clocks = {chess.WHITE: base, chess.BLACK: base}
        self.selected_sq = None
        self.legal_targets = []
        self.last_move = None
        self.prev_eval = None
        self.game_over = False
        self.waiting_player = False
        self.engine_thinking = False
        pname = "Vous (Blancs)" if self.player_color == chess.WHITE else "Vous (Noirs)"
        self.player_frame._time_label.config(
            text=self._fmt(self.clocks[self.player_color]))
        engine_color = not self.player_color
        self.engine_frame._time_label.config(
            text=self._fmt(self.clocks[engine_color]))
        tk.Label(self.player_frame, text=pname, bg="#2A2A2A", fg="#F0D9B5",
                 font=("Helvetica", 10, "bold")).place(x=12, y=8)
        if self.engine:
            try:
                self.engine.configure({
                    "UCI_LimitStrength": True,
                    "UCI_Elo": STOCKFISH_ELO_live
                })
            except Exception:
                pass
        self._draw_board()
        self._update_history()
        self._start_clock_tick()
        if self.player_color == chess.WHITE:
            self._begin_player_turn()
        else:
            self.after(300, self._begin_engine_turn)
    def _load_engine(self):
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            self._set_status("✓ Stockfish chargé", "#7FC97F")
        except Exception as e:
            self.engine = None
            self._set_status(f"✗ Stockfish introuvable : {e}", "#FF6B6B")
    def _fmt(self, secs):
        secs = max(0, int(secs))
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h: return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    def _start_clock_tick(self):
        self._clock_last = time.time()
        self._tick()
    def _tick(self):
        if self.game_over: return
        now = time.time()
        dt  = now - self._clock_last
        self._clock_last = now
        if self.active_clock is not None:
            self.clocks[self.active_clock] -= dt
            if self.clocks[self.active_clock] <= 0:
                self.clocks[self.active_clock] = 0
                self._update_clock_display()
                loser = "joueur" if self.active_clock == self.player_color else "moteur"
                self._end_game(f"Temps écoulé — {'Vous perdez' if loser == 'joueur' else 'Stockfish perd'} !")
                return
            self._update_clock_display()
        self.after(100, self._tick)
    def _update_clock_display(self):
        pc = self.player_color
        ec = not self.player_color
        pt = self.clocks[pc]
        et = self.clocks[ec]
        p_fg = "#FF6B6B" if pt < 60 else ("#FFC107" if pt < 300 else "#EEEEEE")
        e_fg = "#FF6B6B" if et < 60 else ("#FFC107" if et < 300 else "#EEEEEE")
        self.player_frame._time_label.config(text=self._fmt(pt), fg=p_fg)
        self.engine_frame._time_label.config(text=self._fmt(et), fg=e_fg)
        self.player_frame.config(bg="#2A4A2A" if self.active_clock == pc else "#2A2A2A")
        self.engine_frame.config(bg="#2A4A2A" if self.active_clock == ec else "#2A2A2A")
        self.player_frame._time_label.config(bg="#2A4A2A" if self.active_clock == pc else "#2A2A2A")
        self.engine_frame._time_label.config(bg="#2A4A2A" if self.active_clock == ec else "#2A2A2A")
    def _begin_player_turn(self):
        self.waiting_player = True
        self.active_clock   = self.player_color
        self.move_entry.config(state="normal")
        self.play_btn.config(state="normal")
        self.move_entry.focus_set()
        self._set_status("À vous de jouer…", "#7FC97F")
    def _play_text_move(self):
        if not self.waiting_player or self.game_over: return
        raw = self.move_var.get().strip()
        if not raw: return
        try:
            move = self.board.parse_san(raw)
        except Exception:
            try:
                move = self.board.parse_uci(raw)
            except Exception:
                self._set_status("✗ Coup illégal ou non reconnu", "#FF6B6B")
                return
        if move not in self.board.legal_moves:
            self._set_status("✗ Coup illégal", "#FF6B6B")
            return
        self._apply_player_move(move)
    def _on_board_click(self, event):
        if not self.waiting_player or self.game_over: return
        col = (event.x - 12) // SQ_SIZE
        row = (event.y - 12) // SQ_SIZE
        if not (0 <= col <= 7 and 0 <= row <= 7): return
        if self.player_color == chess.WHITE:
            sq = chess.square(col, 7 - row)
        else:
            sq = chess.square(7 - col, row)
        piece = self.board.piece_at(sq)
        if self.selected_sq is None:
            if piece and piece.color == self.player_color:
                self.selected_sq  = sq
                self.legal_targets = [m.to_square for m in self.board.legal_moves
                                      if m.from_square == sq]
                self._draw_board()
            return
        if sq in self.legal_targets:
            # Promotion automatique en dame
            move = None
            for m in self.board.legal_moves:
                if m.from_square == self.selected_sq and m.to_square == sq:
                    if m.promotion:
                        if m.promotion == chess.QUEEN:
                            move = m; break
                    else:
                        move = m; break
            if move:
                self.selected_sq  = None
                self.legal_targets = []
                self._apply_player_move(move)
                return
        if piece and piece.color == self.player_color:
            self.selected_sq  = sq
            self.legal_targets = [m.to_square for m in self.board.legal_moves
                                  if m.from_square == sq]
        else:
            self.selected_sq  = None
            self.legal_targets = []
        self._draw_board()
    def _apply_player_move(self, move):
        self.waiting_player = False
        self.active_clock   = None
        self.move_entry.config(state="disabled")
        self.play_btn.config(state="disabled")
        san = self.board.san(move)
        self.board.push(move)
        move_count = len(self.board.move_stack)
        if self.bonus_move and move_count == self.bonus_move *2:
            self.clocks[chess.WHITE]+=self.bonus_time
            self.clocks[chess.BLACK]+=self.bonus_time
            self.increment = self.bonus_increment_after_bonus
        self.clocks[self.player_color]+= self.increment
        self.last_move = move
        self.selected_sq = None
        self.legal_targets = []
        self.move_var.set("")
        self._draw_board()
        self._update_history()
        self._set_status(f"✓ Coup joué : {san}", "#7FC97F")
        if self.board.is_game_over():
            self._end_game(self._result_str())
            return
        self.after(200, self._begin_engine_turn)
    def _begin_engine_turn(self):
        if self.game_over: return
        self.engine_thinking = True
        engine_color = not self.player_color
        self.active_clock = engine_color
        self._set_status("Stockfish réfléchit…", "#FFC107")
        threading.Thread(target=self._engine_think_thread, daemon=True).start()
    def _engine_think_thread(self):
        engine_color = not self.player_color
        remaining    = self.clocks[engine_color]
        infos = []
        curr_eval = None
        best_move = None
        if self.engine:
            try:
                infos = self.engine.analyse(
                    self.board,
                    chess.engine.Limit(time=ANALYSIS_TIME),
                    multipv=MULTIPV,
                )
                if infos:
                    info0 = infos[0] if isinstance(infos, list) else infos
                    sc = info0.get("score")
                    if sc and not sc.is_mate():
                        curr_eval = sc.relative.score()
                    pv = info0.get("pv")
                    if pv: best_move = pv[0]
            except Exception:
                pass
            if best_move is None:
                try:
                    result = self.engine.play(self.board, chess.engine.Limit(time=ANALYSIS_TIME))
                    best_move = result.move
                except Exception:
                    pass
        if best_move is None:
            legal = list(self.board.legal_moves)
            best_move = random.choice(legal) if legal else None
        wait = compute_think_time(
            self.board,
            infos if isinstance(infos, list) else [infos],
            self.prev_eval, curr_eval, remaining,
        )
        steps = [
            (wait,        "Stockfish réfléchit…"),
            (wait * 0.55, "Stockfish analyse en profondeur…"),
            (wait * 0.25, "Stockfish finalise son choix…"),
            (5,           "Stockfish joue !"),
        ]
        deadline = time.time() + wait
        while True:
            left = deadline - time.time()
            if left <= 0: break
            for thresh, msg in steps:
                if left <= thresh:
                    self.after(0, lambda m=msg: self._set_status(m, "#FFC107"))
                    break
            time.sleep(0.2)
        self.prev_eval = curr_eval
        self.after(0, lambda: self._apply_engine_move(best_move, curr_eval))
    def _apply_engine_move(self, move, curr_eval):
        winsound.Beep(440,100)
        if self.game_over or move is None: return
        self.engine_thinking = False
        self.active_clock    = None
        san = self.board.san(move)
        self.board.push(move)
        engine_color = not self.player_color
        move_count = len(self.board.move_stack)
        if self.bonus_move and move_count == self.bonus_move *2:
            self.clocks[chess.WHITE]+=self;self.bonus_time
            self.clocks[chess.BLACK]+=self;self.bonus_time
            self.increment =self.bonus_increment_after_bonus
        self.clocks[engine_color]+=self.increment
        self.last_move = move
        self._draw_board()
        self._update_history()
        self._update_eval(curr_eval)
        self._set_status(f"Stockfish joue : {san}", "#B58863")
        if self.board.is_game_over():
            self._end_game(self._result_str())
            return
        self.after(300, self._begin_player_turn)
    def _draw_board(self):
        c = self.canvas
        c.delete("all")
        OFFSET = 12  # marge pour les labels
        in_check = self.board.is_check()
        king_sq  = self.board.king(self.board.turn) if in_check else None
        for sq in chess.SQUARES:
            col = chess.square_file(sq)
            row = chess.square_rank(sq)
            if self.player_color == chess.WHITE:
                x = OFFSET + col * SQ_SIZE
                y = OFFSET + (7 - row) * SQ_SIZE
            else:
                x = OFFSET + (7 - col) * SQ_SIZE
                y = OFFSET + row * SQ_SIZE
            base = LIGHT_SQ if (col + row) % 2 != 0 else DARK_SQ
            if self.last_move and sq in (self.last_move.from_square, self.last_move.to_square):
                color = LAST_CLR
            elif sq == self.selected_sq:
                color = SEL_CLR
            elif sq == king_sq:
                color = CHECK_CLR
            else:
                color = base
            c.create_rectangle(x, y, x + SQ_SIZE, y + SQ_SIZE, fill=color, outline="")
            if sq in self.legal_targets:
                piece_there = self.board.piece_at(sq)
                if piece_there:
                    c.create_oval(x+2, y+2, x+SQ_SIZE-2, y+SQ_SIZE-2,
                                  outline=LEGAL_CLR, width=4, fill="")
                else:
                    r = SQ_SIZE // 6
                    cx2, cy2 = x + SQ_SIZE//2, y + SQ_SIZE//2
                    c.create_oval(cx2-r, cy2-r, cx2+r, cy2+r,
                                  fill=LEGAL_CLR, outline="")
            piece = self.board.piece_at(sq)
            if piece:
                sym = PIECES[piece.symbol()]
                c.create_text(x + SQ_SIZE//2, y + SQ_SIZE//2,
                    text=sym, font=("Segoe UI Symbol", 40), fill="#FAFAFA" if piece.color else "#1A1A1A",
                    tags="piece")
        files = "abcdefgh" if self.player_color == chess.WHITE else "hgfedcba"
        ranks = "87654321" if self.player_color == chess.WHITE else "12345678"
        for i in range(8):
            c.create_text(OFFSET + i * SQ_SIZE + SQ_SIZE//2,
                          OFFSET + 8 * SQ_SIZE + 6,
                          text=files[i], fill="#888", font=("Helvetica", 9))
            c.create_text(6, OFFSET + i * SQ_SIZE + SQ_SIZE//2,
                          text=ranks[i], fill="#888", font=("Helvetica", 9))

        self.fen_var.set(self.board.fen())
    def _update_eval(self, cp):
        if cp is None: return
        pawns = cp / 100.0
        pct = max(0.0, min(1.0, 0.5 + pawns / 20.0))
        self.eval_bar.place(relwidth=pct)
        color = "#4A90D9" if pawns > 0.3 else ("#E24B4A" if pawns < -0.3 else "#888")
        self.eval_bar.config(bg=color)
        sign = "+" if pawns >= 0 else ""
        self.eval_label.config(text=f"{sign}{pawns:.2f}")
    def _update_history(self):
        moves = self.board.move_stack
        san_list = []
        b = chess.Board()
        for m in moves:
            san_list.append(b.san(m))
            b.push(m)
        lines = []
        for i in range(0, len(san_list), 2):
            w = san_list[i]
            bl = san_list[i+1] if i+1 < len(san_list) else ""
            lines.append(f"{i//2+1:>3}. {w:<8} {bl}")
        self.hist_text.config(state="normal")
        self.hist_text.delete("1.0", "end")
        self.hist_text.insert("end", "\n".join(lines))
        self.hist_text.see("end")
        self.hist_text.config(state="disabled")
    def _set_status(self, msg, color="#CCC"):
        self.status_var.set(msg)
        self.status_lbl.config(fg=color)
    def _result_str(self):
        if self.board.is_checkmate():
            winner = not self.board.turn
            return "Vous avez gagné !" if winner == self.player_color else "Stockfish a gagné !"
        if self.board.is_stalemate():    return "Pat — Nulle."
        if self.board.is_insufficient_material(): return "Matériel insuffisant — Nulle."
        if self.board.is_repetition():  return "Répétition — Nulle."
        if self.board.is_fifty_moves(): return "Règle des 50 coups — Nulle."
        return "Fin de partie."
    def _end_game(self, msg):
        self.game_over    = True
        self.active_clock = None
        self.waiting_player = False
        self.move_entry.config(state="disabled")
        self.play_btn.config(state="disabled")
        self._set_status(msg, "#FFC107")
        messagebox.showinfo("Fin de partie", msg)
    def _abandon(self):
        if not self.game_over:
            self._end_game("Vous avez abandonné.")
    def _draw(self):
        if not self.game_over:
            self._end_game("Nulle proposée — acceptée.")
    def _new_game(self):
        if self.game_over or messagebox.askyesno("Nouvelle partie", "Abandonner la partie en cours ?"):
            self.game_over    = True
            self.active_clock = None
            self._show_setup()
    def on_close(self):
        self.game_over = True
        if self.engine:
            try: self.engine.quit()
            except: pass
        self.destroy()
if __name__ == "__main__":
    app = ChessApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
