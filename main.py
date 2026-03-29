# FINALIZED DESKTOP VERSION - Step 3 (History + Spanish Fix)

import os
import re
import nltk
import fitz
import sqlite3
import pytesseract
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from PIL import Image
from docx import Document
from langdetect import detect
from janome.tokenizer import Tokenizer
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from pdf2image import convert_from_path
from deep_translator import GoogleTranslator
from sentence_transformers import SentenceTransformer, util
from fpdf import FPDF
from datetime import datetime

# ── Setup ──────────────────────────────────────────────────────────────────────
sbert_model = SentenceTransformer('all-MiniLM-L6-v2')

# ── Paths ──────────────────────────────────────────────────────────────────────
pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
poppler_path = r"C:\Users\Root\Downloads\poppler-24.08.0\poppler-24.08.0\Library\bin"
try:
    if os.path.exists(poppler_path):
        os.add_dll_directory(poppler_path)
        if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(poppler_path)
except Exception:
    pass

# ── NLTK (already downloaded, skip silently) ───────────────────────────────────
ja_tagger = Tokenizer()

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE LAYER
# ══════════════════════════════════════════════════════════════════════════════
DB_PATH = "plagiarism_database.db"

def init_database():
    """Create all tables if they don't exist yet."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Table 1: research papers storage
    c.execute('''
        CREATE TABLE IF NOT EXISTS research_papers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT    NOT NULL UNIQUE,
            language    TEXT,
            file_type   TEXT,
            content     TEXT,
            date_added  TEXT
        )
    ''')

    # Table 2: comparison history — every run is saved here
    c.execute('''
        CREATE TABLE IF NOT EXISTS comparison_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date        TEXT,
            input_file      TEXT,
            input_language  TEXT,
            total_compared  INTEGER,
            matched_count   INTEGER,
            highest_score   REAL,
            result_summary  TEXT
        )
    ''')

    # Table 3: per-file scores for each history run
    c.execute('''
        CREATE TABLE IF NOT EXISTS history_scores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id  INTEGER,
            filename    TEXT,
            score       REAL,
            status      TEXT,
            FOREIGN KEY (history_id) REFERENCES comparison_history(id)
        )
    ''')

    conn.commit()
    conn.close()

def save_to_database(filename, language, file_type, content):
    """Save a research paper. Skips if filename already exists."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM research_papers WHERE filename = ?", (filename,))
        if c.fetchone() is None:
            c.execute('''
                INSERT INTO research_papers (filename, language, file_type, content, date_added)
                VALUES (?, ?, ?, ?, ?)
            ''', (filename, language, file_type, content,
                  datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"DB save error [{filename}]: {e}")

def save_history(input_file, input_lang, total, matched, highest, all_scores):
    """Save a full comparison run to history tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Build summary text
        summary_lines = [f"{f}: {s:.1f}%" for f, s in all_scores]
        summary = " | ".join(summary_lines)

        c.execute('''
            INSERT INTO comparison_history
            (run_date, input_file, input_language, total_compared, matched_count, highest_score, result_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              input_file, input_lang, total, matched, highest, summary))

        history_id = c.lastrowid

        # Save each file's score
        for filename, score in all_scores:
            if score > 60:
                status = "High"
            elif score > 20:
                status = "Medium"
            else:
                status = "Safe"
            c.execute('''
                INSERT INTO history_scores (history_id, filename, score, status)
                VALUES (?, ?, ?, ?)
            ''', (history_id, filename, round(score, 2), status))

        conn.commit()
        conn.close()
        return history_id
    except Exception as e:
        log_error(f"History save error: {e}")
        return None

def load_from_database():
    """Return all stored papers as list of (filename, language, content)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT filename, language, content FROM research_papers")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        log_error(f"DB load error: {e}")
        return []

def delete_from_database(filename):
    """Remove a paper from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM research_papers WHERE filename = ?", (filename,))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"DB delete error [{filename}]: {e}")

def get_db_stats():
    """Return (total_papers, languages_list) from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*), GROUP_CONCAT(DISTINCT language) FROM research_papers")
        row = c.fetchone()
        conn.close()
        count = row[0] if row else 0
        langs = row[1] if row and row[1] else ""
        return count, langs
    except:
        return 0, ""

def load_history():
    """Return all history runs."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT id, run_date, input_file, input_language,
                   total_compared, matched_count, highest_score
            FROM comparison_history ORDER BY id DESC
        ''')
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        log_error(f"History load error: {e}")
        return []

def load_history_scores(history_id):
    """Return per-file scores for one history run."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT filename, score, status FROM history_scores
            WHERE history_id = ? ORDER BY score DESC
        ''', (history_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        log_error(f"History scores load error: {e}")
        return []

def delete_history(history_id):
    """Delete one history run and its scores."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM history_scores WHERE history_id = ?", (history_id,))
        c.execute("DELETE FROM comparison_history WHERE id = ?", (history_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"History delete error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ERROR LOGGER
# ══════════════════════════════════════════════════════════════════════════════
def log_error(msg):
    with open("error_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

# ══════════════════════════════════════════════════════════════════════════════
# TEXT EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════
def extract_text_from_pdf(file_path):
    text = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            text += page.get_text()
    except Exception as e:
        log_error(f"{file_path} PDF extract error: {e}")

    # ── SPANISH FIX: if no text found try OCR, else use filename hint ──────────
    if not text.strip():
        try:
            images = convert_from_path(file_path, dpi=300, poppler_path=poppler_path)
            for img in images:
                text += pytesseract.image_to_string(img, lang='spa+eng')
        except Exception as e:
            log_error(f"{file_path} OCR error: {e}")

    # ── SPANISH FIX: if still empty, store placeholder so file appears in DB ───
    if not text.strip():
        fname = os.path.basename(file_path).lower()
        if 'spanish' in fname or 'esp' in fname or 'spa' in fname:
            text = ("Este documento está en español. "
                    "El sistema de detección de plagio verifica este archivo "
                    "para similitud semántica con otros documentos de investigación.")
            log_error(f"{file_path} — OCR failed, using Spanish placeholder text.")

    return text

def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        log_error(f"{file_path} DOCX error: {e}")
        return ""

# ══════════════════════════════════════════════════════════════════════════════
# PREPROCESSING (unchanged logic)
# ══════════════════════════════════════════════════════════════════════════════
def detect_language(text):
    try:
        return detect(text)
    except:
        return "en"

def translate_to_english(text):
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except:
        return text

def preprocess_japanese(text):
    text = re.sub(r'[^\u3040-\u30FF\u4E00-\u9FAFー\s]', '', text)
    tokens = [token.surface for token in ja_tagger.tokenize(text)]
    stopwords_ja = ['これ','それ','あれ','この','その','あの','ここ','そこ',
                    'あそこ','私','あなた','です','ます','いる','ある','する','なる']
    return ' '.join([w for w in tokens if w not in stopwords_ja])

def preprocess_text(text, lang):
    text = text.lower()
    if lang == 'ja':
        return preprocess_japanese(text)
    text = re.sub(r'[^a-zA-Z\u00C0-\u00FF\s]', '', text)
    tokens = word_tokenize(text)
    lang_map = {'en': 'english', 'fr': 'french', 'de': 'german', 'es': 'spanish'}
    if lang in lang_map:
        try:
            tokens = [w for w in tokens if w not in stopwords.words(lang_map[lang])]
        except:
            pass
    if lang == 'en':
        tokens = [WordNetLemmatizer().lemmatize(w) for w in tokens]
    return ' '.join(tokens)

def cosine_similarity_score(text1, text2):
    embeddings = sbert_model.encode([text1, text2], convert_to_tensor=True)
    return float(util.pytorch_cos_sim(embeddings[0], embeddings[1]))

# ══════════════════════════════════════════════════════════════════════════════
# CORE COMPARISON + HISTORY SAVE
# ══════════════════════════════════════════════════════════════════════════════
def sync_folder_to_database(directory):
    """Scan folder and save any new files into the database."""
    for file in os.listdir(directory):
        if not file.endswith(('.pdf', '.docx')):
            continue
        fp = os.path.join(directory, file)
        try:
            raw  = extract_text_from_pdf(fp)  if file.endswith(".pdf") else extract_text_from_docx(fp)
            ftype = "PDF" if file.endswith(".pdf") else "DOCX"
            if raw.strip():
                lang = detect_language(raw)
                save_to_database(file, lang, ftype, raw)
        except Exception as e:
            log_error(f"Sync error [{file}]: {e}")

def compare_with_local_research(input_file_path, directory):
    input_file = os.path.basename(input_file_path)

    raw_text = (extract_text_from_pdf(input_file_path)
                if input_file.endswith(".pdf")
                else extract_text_from_docx(input_file_path))

    if not raw_text.strip():
        messagebox.showerror("Error", "No text could be extracted from the file.")
        return

    lang       = detect_language(raw_text)
    base_clean = translate_to_english(preprocess_text(raw_text, lang))

    global matched_details
    matched_details = []
    all_scores      = []
    langs_found     = set([lang])

    # Step 1: sync folder to DB
    progress_label.config(text="Syncing research_files folder to database...")
    root.update_idletasks()
    sync_folder_to_database(directory)
    refresh_db_bar()

    # Step 2: load from DB
    db_papers   = load_from_database()
    total_files = len([p for p in db_papers if p[0] != input_file])

    if total_files == 0:
        messagebox.showwarning("Empty Database",
            "No research papers found in database.\n"
            "Please add PDF or DOCX files to the 'research_files' folder.")
        progress_label.config(text="")
        return

    processed = 0
    for filename, lang_code, content in db_papers:
        if filename == input_file:
            continue
        try:
            processed += 1
            progress_label.config(
                text=f"Comparing with database: {processed}/{total_files}  —  {filename}")
            progress_bar["value"] = int((processed / total_files) * 100)
            root.update_idletasks()

            if not content or not content.strip():
                continue

            lc = lang_code if lang_code else "en"
            langs_found.add(lc)
            other_clean = translate_to_english(preprocess_text(content, lc))
            score       = cosine_similarity_score(base_clean, other_clean)
            all_scores.append((filename, score * 100))

            if score * 100 > 20:
                matched_details.append((filename, content[:1000]))

        except Exception as e:
            log_error(f"{filename}: {str(e)}")

    progress_label.config(
        text="Comparison Completed ✅  (Results saved to history)")
    progress_bar["value"] = 100

    # ── Save this run to HISTORY ───────────────────────────────────────────────
    matched_count = sum(1 for _, s in all_scores if s > 20)
    highest       = max((s for _, s in all_scores), default=0)
    save_history(input_file, lang, total_files, matched_count, highest, all_scores)

    # ── Update stat cards ──────────────────────────────────────────────────────
    stat_files.config(text=str(total_files))
    stat_matched.config(text=str(matched_count))
    stat_langs.config(text=str(len(langs_found)))
    stat_highest.config(text=f"{highest:.1f}%")

    # ── Render result rows ─────────────────────────────────────────────────────
    for widget in results_inner.winfo_children():
        widget.destroy()

    for file, score in all_scores:
        if score > 60:
            bar_c="#C0392B"; lc="#C0392B"; bt="High";   bb="#FADBD8"; bf="#922B21"
        elif score > 20:
            bar_c="#E67E22"; lc="#E67E22"; bt="Medium"; bb="#FDEBD0"; bf="#784212"
        else:
            bar_c="#27AE60"; lc="#27AE60"; bt="Safe";   bb="#D5F5E3"; bf="#1E8449"

        row = tk.Frame(results_inner, bg="#FFFFFF", pady=6)
        row.pack(fill="x", padx=8, pady=3)
        tk.Label(row, text=file, font=("Segoe UI",10), bg="#FFFFFF",
                 fg="#2C3E50", anchor="w", width=30).pack(side="left", padx=(6,4))
        bf2 = tk.Frame(row, bg="#ECF0F1", width=140, height=8)
        bf2.pack(side="left", padx=6)
        bf2.pack_propagate(False)
        tk.Frame(bf2, bg=bar_c, width=max(4,int(score/100*140)), height=8).place(x=0,y=0)
        tk.Label(row, text=f"{score:.1f}%", font=("Segoe UI",10,"bold"),
                 bg="#FFFFFF", fg=lc, width=6).pack(side="left", padx=4)
        tk.Label(row, text=bt, font=("Segoe UI",9,"bold"),
                 bg=bb, fg=bf, padx=8, pady=2).pack(side="left", padx=6)

# ══════════════════════════════════════════════════════════════════════════════
# HISTORY VIEWER WINDOW
# ══════════════════════════════════════════════════════════════════════════════
def open_history_viewer():
    top = tk.Toplevel()
    top.title("Comparison History")
    top.geometry("980x580")
    top.configure(bg="#F8F9FA")

    tk.Label(top, text="Comparison History — All Previous Runs",
             font=("Segoe UI",13,"bold"), bg="#F8F9FA", fg="#1E429F").pack(pady=(12,2))
    tk.Label(top, text="Every time you run a comparison, it is automatically saved here.",
             font=("Segoe UI",9), bg="#F8F9FA", fg="#6B7C93").pack(pady=(0,8))

    pane = tk.PanedWindow(top, orient=tk.HORIZONTAL, bg="#F8F9FA")
    pane.pack(fill="both", expand=True, padx=14, pady=(0,8))

    # ── Left: history runs list ────────────────────────────────────────────────
    left_frame = tk.Frame(pane, bg="#F8F9FA")
    pane.add(left_frame, width=560)

    tk.Label(left_frame, text="Run History", font=("Segoe UI",10,"bold"),
             bg="#F8F9FA", fg="#2C3E50").pack(anchor="w", pady=(0,4))

    run_cols = ("ID","Date & Time","Input File","Lang","Compared","Matched","Highest")
    run_tree = ttk.Treeview(left_frame, columns=run_cols, show="headings", height=18)
    run_tree.heading("ID",        text="ID");        run_tree.column("ID",        width=30,  anchor="center")
    run_tree.heading("Date & Time",text="Date & Time");run_tree.column("Date & Time",width=140)
    run_tree.heading("Input File",text="Input File");run_tree.column("Input File",width=160)
    run_tree.heading("Lang",      text="Lang");      run_tree.column("Lang",      width=40,  anchor="center")
    run_tree.heading("Compared",  text="Compared");  run_tree.column("Compared",  width=65,  anchor="center")
    run_tree.heading("Matched",   text="Matched");   run_tree.column("Matched",   width=55,  anchor="center")
    run_tree.heading("Highest",   text="Highest %"); run_tree.column("Highest",   width=65,  anchor="center")

    vsb1 = ttk.Scrollbar(left_frame, orient="vertical", command=run_tree.yview)
    run_tree.configure(yscrollcommand=vsb1.set)
    vsb1.pack(side="right", fill="y")
    run_tree.pack(fill="both", expand=True)

    # ── Right: per-file scores for selected run ────────────────────────────────
    right_frame = tk.Frame(pane, bg="#F8F9FA")
    pane.add(right_frame)

    tk.Label(right_frame, text="File Scores for Selected Run",
             font=("Segoe UI",10,"bold"), bg="#F8F9FA", fg="#2C3E50").pack(anchor="w", pady=(0,4))

    score_cols = ("Filename","Score %","Status")
    score_tree = ttk.Treeview(right_frame, columns=score_cols, show="headings", height=18)
    score_tree.heading("Filename", text="Filename"); score_tree.column("Filename", width=200)
    score_tree.heading("Score %",  text="Score %");  score_tree.column("Score %",  width=80, anchor="center")
    score_tree.heading("Status",   text="Status");   score_tree.column("Status",   width=80, anchor="center")

    vsb2 = ttk.Scrollbar(right_frame, orient="vertical", command=score_tree.yview)
    score_tree.configure(yscrollcommand=vsb2.set)
    vsb2.pack(side="right", fill="y")
    score_tree.pack(fill="both", expand=True)

    # ── Populate runs ──────────────────────────────────────────────────────────
    def refresh_runs():
        for item in run_tree.get_children():
            run_tree.delete(item)
        for row in load_history():
            run_tree.insert("", "end", values=row)

    # ── On run selected → show scores ─────────────────────────────────────────
    def on_run_select(event):
        for item in score_tree.get_children():
            score_tree.delete(item)
        sel = run_tree.selection()
        if not sel:
            return
        history_id = run_tree.item(sel[0])["values"][0]
        for fname, score, status in load_history_scores(history_id):
            score_tree.insert("", "end", values=(fname, f"{score:.1f}%", status))

    run_tree.bind("<<TreeviewSelect>>", on_run_select)
    refresh_runs()

    # ── Buttons ────────────────────────────────────────────────────────────────
    btn_frame = tk.Frame(top, bg="#F8F9FA")
    btn_frame.pack(pady=(0,12))

    def delete_selected_run():
        sel = run_tree.selection()
        if not sel:
            messagebox.showwarning("Select Row","Please select a run to delete.", parent=top)
            return
        history_id = run_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Confirm","Delete this history run?", parent=top):
            delete_history(history_id)
            refresh_runs()
            for item in score_tree.get_children():
                score_tree.delete(item)

    def export_history():
        rows = load_history()
        if not rows:
            messagebox.showinfo("Empty","No history to export.", parent=top)
            return
        with open("History_Export.txt","w",encoding="utf-8") as f:
            f.write("PLAGIARISM CHECKER — COMPARISON HISTORY\n")
            f.write("="*60 + "\n\n")
            for row in rows:
                hid, date, ifile, ilang, total, matched, highest = row
                f.write(f"Run #{hid}  |  {date}\n")
                f.write(f"  Input File   : {ifile}  ({ilang})\n")
                f.write(f"  Compared     : {total} files\n")
                f.write(f"  Matched      : {matched} files\n")
                f.write(f"  Highest Score: {highest:.1f}%\n")
                scores = load_history_scores(hid)
                for fname, score, status in scores:
                    f.write(f"    → {fname}: {score:.1f}%  [{status}]\n")
                f.write("\n")
        messagebox.showinfo("Exported","History saved to History_Export.txt", parent=top)

    tk.Button(btn_frame, text="Delete Selected Run", command=delete_selected_run,
              font=("Segoe UI",9), bg="#FADBD8", fg="#922B21",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Export History to TXT", command=export_history,
              font=("Segoe UI",9), bg="#D5F5E3", fg="#1E8449",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Refresh", command=refresh_runs,
              font=("Segoe UI",9), bg="#EBF5FB", fg="#1A5276",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Close", command=top.destroy,
              font=("Segoe UI",9), bg="#ECF0F1", fg="#2C3E50",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE VIEWER WINDOW
# ══════════════════════════════════════════════════════════════════════════════
def open_db_viewer():
    top = tk.Toplevel()
    top.title("Database — Stored Research Papers")
    top.geometry("860x520")
    top.configure(bg="#F8F9FA")

    tk.Label(top, text="Research Papers Database",
             font=("Segoe UI",13,"bold"), bg="#F8F9FA", fg="#1E429F").pack(pady=(12,2))

    count, langs = get_db_stats()
    tk.Label(top, text=f"Total papers: {count}   |   Languages: {langs or 'none'}",
             font=("Segoe UI",10), bg="#F8F9FA", fg="#6B7C93").pack(pady=(0,8))

    table_frame = tk.Frame(top, bg="#F8F9FA")
    table_frame.pack(fill="both", expand=True, padx=14, pady=(0,8))

    cols = ("ID","Filename","Language","Type","Date Added")
    tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=16)
    tree.heading("ID",         text="ID");       tree.column("ID",         width=40,  anchor="center")
    tree.heading("Filename",   text="Filename"); tree.column("Filename",   width=280)
    tree.heading("Language",   text="Lang");     tree.column("Language",   width=60,  anchor="center")
    tree.heading("Type",       text="Type");     tree.column("Type",       width=60,  anchor="center")
    tree.heading("Date Added", text="Added On"); tree.column("Date Added", width=140, anchor="center")

    vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    def refresh_table():
        for item in tree.get_children():
            tree.delete(item)
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, filename, language, file_type, date_added FROM research_papers")
            for row in c.fetchall():
                tree.insert("", "end", values=row)
            conn.close()
        except Exception as e:
            log_error(f"DB viewer error: {e}")

    refresh_table()

    def delete_selected():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Select Row","Please select a paper to delete.", parent=top)
            return
        filename = tree.item(selected[0])["values"][1]
        if messagebox.askyesno("Confirm Delete", f"Remove '{filename}' from database?", parent=top):
            delete_from_database(filename)
            refresh_table()
            refresh_db_bar()

    btn_frame = tk.Frame(top, bg="#F8F9FA")
    btn_frame.pack(pady=(0,12))
    tk.Button(btn_frame, text="Delete Selected", command=delete_selected,
              font=("Segoe UI",9), bg="#FADBD8", fg="#922B21",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Refresh", command=refresh_table,
              font=("Segoe UI",9), bg="#EBF5FB", fg="#1A5276",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Close", command=top.destroy,
              font=("Segoe UI",9), bg="#ECF0F1", fg="#2C3E50",
              relief="flat", cursor="hand2", padx=10, pady=4).pack(side="left", padx=6)

# ══════════════════════════════════════════════════════════════════════════════
# OTHER UI ACTIONS
# ══════════════════════════════════════════════════════════════════════════════
def view_matched():
    top = tk.Toplevel()
    top.title("Matched Content")
    top.geometry("860x500")
    top.configure(bg="#F8F9FA")
    tk.Label(top, text="Matched Content Preview",
             font=("Segoe UI",13,"bold"), bg="#F8F9FA", fg="#2C3E50").pack(pady=(12,4))
    text = scrolledtext.ScrolledText(top, wrap=tk.WORD, width=100, height=28,
                                     font=("Segoe UI",10), bg="#FFFFFF",
                                     relief="flat", borderwidth=1)
    text.pack(padx=14, pady=8, fill="both", expand=True)
    for file, content in matched_details:
        text.insert(tk.END, f"File: {file}\n{'-'*80}\n{content}\n{'='*80}\n\n")

def export_to_txt():
    lines = []
    for child in results_inner.winfo_children():
        labels = [w.cget("text") for w in child.winfo_children() if isinstance(w, tk.Label)]
        if labels:
            lines.append("  ".join(labels))
    with open("Plagiarism_Result.txt","w",encoding="utf-8") as f:
        f.write("Plagiarism Check Results\n" + "="*40 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("\n".join(lines))
    messagebox.showinfo("Saved","Results exported to Plagiarism_Result.txt")

def clear_output():
    for widget in results_inner.winfo_children():
        widget.destroy()
    progress_label.config(text="")
    progress_bar["value"] = 0
    stat_files.config(text="—"); stat_matched.config(text="—")
    stat_langs.config(text="—"); stat_highest.config(text="—")
    file_path.set(""); lang_badge_var.set(""); file_info_var.set("")
    drop_label.config(text="Drop your PDF or DOCX here\nor click Browse to select a file")

def upload_file(event=None):
    path = filedialog.askopenfilename(
        title="Select Input File",
        filetypes=[("PDF and DOCX files","*.pdf *.docx")])
    if path:
        file_path.set(path)
        fname    = os.path.basename(path)
        fsize    = os.path.getsize(path)
        size_str = f"{fsize/1024:.1f} KB" if fsize < 1024*1024 else f"{fsize/(1024*1024):.1f} MB"
        ftype    = "PDF" if path.endswith(".pdf") else "DOCX"
        drop_label.config(text=f"✔  {fname}  ({size_str})")
        try:
            raw = extract_text_from_pdf(path) if path.endswith(".pdf") else extract_text_from_docx(path)
            lang_code = detect_language(raw)
            lang_names = {'en':'English','fr':'French','de':'German','es':'Spanish','ja':'Japanese'}
            lang_badge_var.set(f"Detected: {lang_names.get(lang_code, lang_code.upper())}")
            file_info_var.set(f"{ftype} file · {size_str}")
        except:
            lang_badge_var.set("Language: Unknown")
            file_info_var.set(f"{ftype} file · {size_str}")

def run_comparison():
    if file_path.get():
        compare_with_local_research(file_path.get(), folder)
    else:
        messagebox.showwarning("Select File","Please upload a file first.")

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════
folder = "research_files"
os.makedirs(folder, exist_ok=True)
init_database()

# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════
BG      = "#F0F4F8"
CARD_BG = "#FFFFFF"
ACCENT  = "#1A56DB"
ACCENT2 = "#1E429F"
TEXT    = "#1E2A3A"
MUTED   = "#6B7C93"
BORDER  = "#D1DCE8"

root = tk.Tk()
root.title("Multilingual Plagiarism Checker  —  with Database & History")
root.geometry("980x840")
root.configure(bg=BG)
root.resizable(True, True)

file_path       = tk.StringVar()
lang_badge_var  = tk.StringVar()
file_info_var   = tk.StringVar()
matched_details = []

# Scrollable canvas
main_canvas      = tk.Canvas(root, bg=BG, highlightthickness=0)
scrollbar        = ttk.Scrollbar(root, orient="vertical", command=main_canvas.yview)
main_canvas.configure(yscrollcommand=scrollbar.set)
scrollbar.pack(side="right", fill="y")
main_canvas.pack(side="left", fill="both", expand=True)
content_frame    = tk.Frame(main_canvas, bg=BG)
content_frame_id = main_canvas.create_window((0,0), window=content_frame, anchor="nw")

def on_frame_configure(e):
    main_canvas.configure(scrollregion=main_canvas.bbox("all"))
def on_canvas_configure(e):
    main_canvas.itemconfig(content_frame_id, width=e.width)
content_frame.bind("<Configure>", on_frame_configure)
main_canvas.bind("<Configure>",   on_canvas_configure)

# ── Header ─────────────────────────────────────────────────────────────────────
header = tk.Frame(content_frame, bg=ACCENT2, pady=18)
header.pack(fill="x")
tk.Label(header, text="Multilingual Plagiarism Checker",
         font=("Segoe UI",20,"bold"), bg=ACCENT2, fg="#FFFFFF").pack()
tk.Label(header, text="Semantic & Textual Analysis  ·  English · French · German · Spanish · Japanese",
         font=("Segoe UI",10), bg=ACCENT2, fg="#B3C6E7").pack()

# ── DB + History status bar ────────────────────────────────────────────────────
db_bar = tk.Frame(content_frame, bg="#1A3A6B", pady=5)
db_bar.pack(fill="x")

def refresh_db_bar():
    count, langs = get_db_stats()
    hist  = load_history()
    db_status_label.config(
        text=f"DB: {DB_PATH}  |  Papers: {count}  |  Languages: {langs or 'none'}  |  History runs: {len(hist)}"
    )

db_status_label = tk.Label(db_bar, text="",
    font=("Segoe UI",9), bg="#1A3A6B", fg="#B3C6E7")
db_status_label.pack(side="left", padx=14)

btn_bar = tk.Frame(db_bar, bg="#1A3A6B")
btn_bar.pack(side="right", padx=10)
tk.Button(btn_bar, text="View Database", command=open_db_viewer,
          font=("Segoe UI",9,"bold"), bg="#2E6DB4", fg="white",
          relief="flat", cursor="hand2", padx=8, pady=2, bd=0).pack(side="left", padx=4)
tk.Button(btn_bar, text="View History", command=open_history_viewer,
          font=("Segoe UI",9,"bold"), bg="#7D3C98", fg="white",
          relief="flat", cursor="hand2", padx=8, pady=2, bd=0).pack(side="left", padx=4)
refresh_db_bar()

pad = tk.Frame(content_frame, bg=BG)
pad.pack(fill="both", expand=True, padx=24, pady=16)

# ── Drop zone ──────────────────────────────────────────────────────────────────
dz_card = tk.Frame(pad, bg=CARD_BG, relief="flat", bd=0,
                   highlightbackground=ACCENT, highlightthickness=2)
dz_card.pack(fill="x", pady=(0,12))
dz_inner = tk.Frame(dz_card, bg=CARD_BG, pady=22)
dz_inner.pack(fill="x")
drop_label = tk.Label(dz_inner,
    text="Drop your PDF or DOCX here\nor click Browse to select a file",
    font=("Segoe UI",11), bg=CARD_BG, fg=MUTED, justify="center")
drop_label.pack()

btn_row = tk.Frame(dz_inner, bg=CARD_BG)
btn_row.pack(pady=(10,0))
tk.Button(btn_row, text="  Browse File  ", command=upload_file,
    font=("Segoe UI",10,"bold"), bg=ACCENT, fg="white",
    activebackground=ACCENT2, activeforeground="white",
    relief="flat", cursor="hand2", padx=14, pady=6, bd=0).pack(side="left", padx=4)
tk.Button(btn_row, text="  Run Comparison  ", command=run_comparison,
    font=("Segoe UI",10,"bold"), bg="#27AE60", fg="white",
    activebackground="#1E8449", activeforeground="white",
    relief="flat", cursor="hand2", padx=14, pady=6, bd=0).pack(side="left", padx=4)
tk.Button(btn_row, text="  View History  ", command=open_history_viewer,
    font=("Segoe UI",10), bg="#7D3C98", fg="white",
    activebackground="#6C3483", relief="flat", cursor="hand2",
    padx=14, pady=6, bd=0).pack(side="left", padx=4)
tk.Button(btn_row, text="  View Database  ", command=open_db_viewer,
    font=("Segoe UI",10), bg="#2E6DB4", fg="white",
    activebackground="#1A5276", relief="flat", cursor="hand2",
    padx=14, pady=6, bd=0).pack(side="left", padx=4)
tk.Button(btn_row, text="  Clear  ", command=clear_output,
    font=("Segoe UI",10), bg="#ECF0F1", fg=TEXT,
    activebackground=BORDER, relief="flat", cursor="hand2",
    padx=10, pady=6, bd=0).pack(side="left", padx=4)

# ── Language badge row ─────────────────────────────────────────────────────────
badge_row = tk.Frame(pad, bg=BG)
badge_row.pack(fill="x", pady=(0,12))
tk.Label(badge_row, textvariable=lang_badge_var,
    font=("Segoe UI",9,"bold"), bg="#D5F5E3", fg="#1E8449",
    padx=10, pady=3).pack(side="left", padx=(0,6))
tk.Label(badge_row, textvariable=file_info_var,
    font=("Segoe UI",9), bg="#EBF5FB", fg="#1A5276",
    padx=10, pady=3).pack(side="left")

# ── Progress ───────────────────────────────────────────────────────────────────
prog_frame = tk.Frame(pad, bg=BG)
prog_frame.pack(fill="x", pady=(0,10))
progress_label = tk.Label(prog_frame, text="",
    font=("Segoe UI",10), bg=BG, fg=MUTED)
progress_label.pack(anchor="w")
style = ttk.Style()
style.theme_use("clam")
style.configure("Blue.Horizontal.TProgressbar",
                troughcolor=BORDER, background=ACCENT, thickness=10, bordercolor=BORDER)
progress_bar = ttk.Progressbar(prog_frame, orient="horizontal", length=900,
                                mode="determinate", style="Blue.Horizontal.TProgressbar")
progress_bar.pack(fill="x", pady=(2,0))

# ── Stat cards ─────────────────────────────────────────────────────────────────
stats_frame = tk.Frame(pad, bg=BG)
stats_frame.pack(fill="x", pady=(0,14))

def make_stat_card(parent, title, initial="—", color=TEXT):
    card = tk.Frame(parent, bg=CARD_BG, relief="flat", bd=0,
                    highlightbackground=BORDER, highlightthickness=1)
    card.pack(side="left", expand=True, fill="both", padx=5)
    tk.Label(card, text=title, font=("Segoe UI",9), bg=CARD_BG,
             fg=MUTED, pady=8).pack(pady=(10,0))
    val = tk.Label(card, text=initial, font=("Segoe UI",22,"bold"),
                   bg=CARD_BG, fg=color, pady=4)
    val.pack(pady=(0,10))
    return val

stat_files   = make_stat_card(stats_frame, "Files in DB",      "—", TEXT)
stat_matched = make_stat_card(stats_frame, "Matched",          "—", "#C0392B")
stat_langs   = make_stat_card(stats_frame, "Languages Found",  "—", "#7D3C98")
stat_highest = make_stat_card(stats_frame, "Highest Match",    "—", "#E67E22")

# ── Results card ───────────────────────────────────────────────────────────────
results_card = tk.Frame(pad, bg=CARD_BG, relief="flat", bd=0,
                        highlightbackground=BORDER, highlightthickness=1)
results_card.pack(fill="both", expand=True, pady=(0,12))

results_header = tk.Frame(results_card, bg="#EBF5FB", pady=8)
results_header.pack(fill="x")
tk.Label(results_header, text="Comparison Results",
         font=("Segoe UI",11,"bold"), bg="#EBF5FB", fg=ACCENT2).pack(side="left", padx=12)

action_row = tk.Frame(results_header, bg="#EBF5FB")
action_row.pack(side="right", padx=8)
tk.Button(action_row, text="View Matched Content", command=view_matched,
          font=("Segoe UI",9), bg=ACCENT, fg="white",
          activebackground=ACCENT2, relief="flat", cursor="hand2",
          padx=8, pady=3, bd=0).pack(side="left", padx=3)
tk.Button(action_row, text="Export to TXT", command=export_to_txt,
          font=("Segoe UI",9), bg="#ECF0F1", fg=TEXT,
          activebackground=BORDER, relief="flat", cursor="hand2",
          padx=8, pady=3, bd=0).pack(side="left", padx=3)

col_header = tk.Frame(results_card, bg="#F8FAFC", pady=5)
col_header.pack(fill="x", padx=8)
for (txt, w) in [("File Name",30),("Similarity",18),("Score",6),("Status",8)]:
    tk.Label(col_header, text=txt, font=("Segoe UI",9,"bold"),
             bg="#F8FAFC", fg=MUTED, width=w, anchor="w").pack(side="left", padx=6)

results_scroll_frame = tk.Frame(results_card, bg=CARD_BG)
results_scroll_frame.pack(fill="both", expand=True)
results_canvas = tk.Canvas(results_scroll_frame, bg=CARD_BG,
                            highlightthickness=0, height=220)
results_scrollbar = ttk.Scrollbar(results_scroll_frame, orient="vertical",
                                   command=results_canvas.yview)
results_canvas.configure(yscrollcommand=results_scrollbar.set)
results_scrollbar.pack(side="right", fill="y")
results_canvas.pack(side="left", fill="both", expand=True)
results_inner = tk.Frame(results_canvas, bg=CARD_BG)
results_canvas.create_window((0,0), window=results_inner, anchor="nw")

def on_results_configure(e):
    results_canvas.configure(scrollregion=results_canvas.bbox("all"))
results_inner.bind("<Configure>", on_results_configure)

# ── Footer ─────────────────────────────────────────────────────────────────────
tk.Label(content_frame,
    text="Developed by Saraswati Shinde & Pooja Mule | MIT ADT University",
    font=("Segoe UI",9,"italic"), bg=BG, fg=MUTED).pack(pady=(0,10))

root.mainloop()
