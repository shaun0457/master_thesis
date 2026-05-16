# me_docs.py (修正模型名稱的最終版)
from dataclasses import dataclass
import numpy as np
import os, json, glob, hashlib, re
import joblib
import scipy.sparse as sp
from typing import List, Dict, Any, Optional

import fitz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from langchain_google_genai import GoogleGenerativeAIEmbeddings

try:
    # 【核心修正】更換為更穩定的嵌入模型版本
    _EMB = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
except Exception as e:
    print(f"[ERROR] 無法初始化 GoogleGenerativeAIEmbeddings: {e}. 請檢查您的 Google Cloud 認證。")
    _EMB = None

# ... (檔案的其餘部分保持完全不變) ...

@dataclass
class PageMeta:
    doc_id: str
    page: int
    text: str

class DocIndex:
    def __init__(self, pages: List[PageMeta], vectorizer: TfidfVectorizer, matrix):
        self.pages = pages
        self.vectorizer = vectorizer
        self.matrix = matrix
        self.embeddings = None

    def build_dense(self):
        global _EMB
        if _EMB is None or not self.pages: return
        print("[INFO] 正在為 RAG 索引建立高密度向量嵌入...")
        texts = [p.text for p in self.pages]
        try:
            vecs = _EMB.embed_documents(texts)
            X = np.array(vecs, dtype="float32")
            X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-8)
            self.embeddings = X
            print("[INFO] 高密度向量嵌入建立成功。")
        except Exception as e:
            print(f"[ERROR] 建立高密度向量嵌入時失敗: {e}")

    def _q_dense(self, q: str) -> np.ndarray | None:
        global _EMB
        if _EMB is None or self.embeddings is None: return None
        try:
            v = np.array(_EMB.embed_query(q), dtype="float32")
            v /= (np.linalg.norm(v) + 1e-8)
            return v
        except Exception as e:
            print(f"[ERROR] 查詢向量化時失敗: {e}")
            return None

    def search(self, query: str, k: int = 8, doc_whitelist: Optional[List[str]] = None, mode: str = "hybrid",
               alpha: float = 0.5) -> List[Dict[str, Any]]:
        allowed = set(doc_whitelist) if doc_whitelist else None
        N = len(self.pages)
        if N == 0: return []
        sparse_scores = np.zeros(N, dtype="float32")
        if self.vectorizer is not None and self.matrix is not None:
            qv = self.vectorizer.transform([query])
            sparse_scores = cosine_similarity(qv, self.matrix).ravel()
        dense_scores = np.zeros(N, dtype="float32")
        qd = self._q_dense(query)
        if qd is not None and self.embeddings is not None:
            dense_scores = self.embeddings @ qd
        mode = (mode or "hybrid").lower()
        if mode == "sparse":
            final = sparse_scores
        elif mode == "dense":
            final = dense_scores
        else:
            def norm(x):
                x = x - np.min(x);
                r = (np.max(x) - np.min(x)) or 1.0
                return x / r
            final = alpha * norm(sparse_scores) + (1 - alpha) * norm(dense_scores)
        ranked = np.argsort(-final)
        hits = []
        for idx in ranked:
            p = self.pages[idx]
            if allowed and p.doc_id not in allowed: continue
            hits.append({"doc_id": p.doc_id, "page": p.page, "score": float(final[idx]),
                         "preview": (p.text[:220] + "…") if p.text else ""})
            if len(hits) >= k: break
        return hits

def _clean(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t

def build_index(doc_paths: List[str]) -> DocIndex:
    pages: List[PageMeta] = []
    print(f"[INFO] 正在處理 {len(doc_paths)} 份文件...")
    for path in doc_paths:
        doc_id = os.path.basename(path)
        try:
            if path.lower().endswith(".pdf"):
                doc = fitz.open(path)
                print(f"  - 正在處理 PDF '{doc_id}', 共 {len(doc)} 頁。")
                for i, page in enumerate(doc, start=1):
                    full_text = page.get_text("text") or ""
                    try:
                        import camelot  # lazy import — optional dependency
                        tables = camelot.read_pdf(path, pages=str(i), flavor='lattice')
                        if tables.n > 0:
                            print(f"    > 在第 {i} 頁找到 {tables.n} 個表格。")
                            for table in tables:
                                markdown_table = table.df.to_markdown(index=False)
                                full_text += f"\n\n--- 表格內容開始 ---\n{markdown_table}\n--- 表格內容結束 ---\n"
                    except Exception:
                        pass
                    if full_text.strip():
                        pages.append(PageMeta(doc_id=doc_id, page=i, text=_clean(full_text)))
                doc.close()
            elif path.lower().endswith(".md"):
                print(f"  - 正在處理 Markdown '{doc_id}'。")
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
                if text.strip():
                    pages.append(PageMeta(doc_id=doc_id, page=1, text=_clean(text)))
        except Exception as e:
            print(f"[ERROR] 處理文件 '{doc_id}' 時失敗: {e}")
            continue
    print(f"[INFO] 成功從 {len(pages)} 個頁面/文件中提取內容。")
    corpus = [p.text for p in pages] or [""]
    vec = TfidfVectorizer(ngram_range=(1, 2), max_features=50_000, stop_words=None)
    X = vec.fit_transform(corpus)
    idx = DocIndex(pages, vec, X)
    idx.build_dense()
    return idx

def read_chunk(index: DocIndex, doc_id: str, page: int, max_chars: int = 4000) -> Dict[str, Any]:
    for p in index.pages:
        if p.doc_id == doc_id and p.page == page:
            return {"doc_id": doc_id, "page": page, "text": p.text[:max_chars]}
    return {"doc_id": doc_id, "page": page, "text": ""}

def load_or_build_index(doc_dir: str, cache_dir: str = ".rag_index"):
    if not os.path.isdir(doc_dir):
        raise FileNotFoundError(f"提供的文件目錄不存在: {doc_dir}")
    pdf_paths = sorted(glob.glob(os.path.join(doc_dir, "*.pdf")))
    md_paths = sorted(glob.glob(os.path.join(doc_dir, "*.md")))
    all_paths = pdf_paths + md_paths
    if not all_paths:
        raise FileNotFoundError(f"在目錄中找不到任何 .pdf 或 .md 檔案: {doc_dir}")
    key = _fingerprint(all_paths)
    cdir = os.path.join(cache_dir, key)
    idx = _load_index(cdir)
    if idx is not None:
        return idx, True
    idx = build_index(all_paths)
    _save_index(cdir, idx)
    return idx, False

def _fingerprint(paths: list[str]) -> str:
    h = hashlib.md5();
    h.update(str(fitz.__doc__).encode())
    for p in sorted(paths):
        try:
            st = os.stat(p);
            h.update(f"{os.path.basename(p)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8"))
        except FileNotFoundError:
            continue
    return h.hexdigest()

def _save_index(cache_dir: str, idx: "DocIndex"):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "pages.jsonl"), "w", encoding="utf-8") as f:
        for p in idx.pages: f.write(json.dumps({"doc_id": p.doc_id, "page": p.page, "text": p.text}, ensure_ascii=False) + "\n")
    joblib.dump(idx.vectorizer, os.path.join(cache_dir, "tfidf_vectorizer.joblib"))
    sp.save_npz(os.path.join(cache_dir, "tfidf_matrix.npz"), idx.matrix)
    if idx.embeddings is not None: np.save(os.path.join(cache_dir, "embeddings.npy"), idx.embeddings)

def _load_index(cache_dir: str) -> "DocIndex | None":
    try:
        vec = joblib.load(os.path.join(cache_dir, "tfidf_vectorizer.joblib"))
        X = sp.load_npz(os.path.join(cache_dir, "tfidf_matrix.npz"))
        pages = []
        with open(os.path.join(cache_dir, "pages.jsonl"), "r", encoding="utf-8") as f:
            for line in f: pages.append(PageMeta(**json.loads(line)))
        idx = DocIndex(pages, vec, X)
        emb_path = os.path.join(cache_dir, "embeddings.npy")
        if os.path.exists(emb_path): idx.embeddings = np.load(emb_path)
        return idx
    except Exception:

        return None
