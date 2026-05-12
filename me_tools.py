import json, re, os, random
from typing import Any, Dict, List, Optional, Callable
import bb_tools
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from run_logger import get_run_logger
from me_docs import DocIndex, read_chunk, load_or_build_index
from common import llm, get_seed, set_global_seeds

DOC_INDEX: Optional[DocIndex] = None

@tool("me_write_fact")
def me_write_fact(section: str, summary: str, uri: str = "", topic_id: str = "", owner: str = "") -> str:
    """
    Write a short fact/summary to central blackboard (facts/datasets/citations/open_issues).
    Returns JSON string with artifact_id (for t_first/read/reuse/orphan).
    """
    out = bb_tools.bb_write(
        run_id=os.environ.get("RUN_ID"),
        topic_id=topic_id or os.environ.get("TOPIC_ID", ""),
        section=section,
        content_preview=summary,
        created_by="ME",
        uri=uri,
        intended_owner=owner or os.environ.get("OWNER", "")
    )
    return json.dumps(out, ensure_ascii=False)

@tool("me_warmup_read")
def me_warmup_read() -> str:
    """
    Suggest the agent to first call read_blackboard(keys=["facts","datasets"], limit=4).
    This nudges an initial blackboard read so bb_read events are emitted for latency/reuse metrics.
    """
    return json.dumps(
        {"status": "ok",
         "suggest": "read_blackboard(keys=[\"facts\",\"datasets\"],limit=4)先行"},
        ensure_ascii=False
    )

def init_me_index_from_dir(doc_dir: str, cache_dir: str = ".rag_index") -> bool:
    set_global_seeds(get_seed())
    global DOC_INDEX
    idx, used_cache = load_or_build_index(doc_dir, cache_dir=cache_dir)
    DOC_INDEX = idx
    return used_cache

# ---- lightweight synonyms ----
_SYNONYMS = {
    "stiction": ["sticking", "valve sticking"],
    "reactor temperature": ["reactor temp", "Tr", "temperature control"],
    "stripper": ["product stripper", "stripping column"],
}
def _syn_expand(q: str) -> List[str]:
    out = [q]
    for k, vs in _SYNONYMS.items():
        if k.lower() in q.lower():
            out.extend(vs)
    seen = set(); uniq = []
    for s in out:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return uniq

# ---- helpers ----
_CITE_RE = re.compile(r"\[[^\[\]\n]+?\.(?:pdf|md|mdx)\s+p\.\s*\d+\]", re.I)
# 新增：條列偵測 & 引用工具
_BULLET_RE = re.compile(r"^\s*(?:[-*•\u2022]|\d+\.)\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")     # Markdown 標題
_TABLE_RE   = re.compile(r"^\s*\|")            # Markdown 表格列
_LAST_CITE_AT_END_RE = re.compile(r"\[[^\[\]\n]+?\.(?:pdf|md|mdx)\s+p\.\s*\d+\]\s*$", re.I)
_ANY_CITE_RE = re.compile(r"\[[^\[\]\n]+?\.(?:pdf|md|mdx)\s+p\.\s*\d+\]", re.I)
_TOKEN_RE = re.compile(r"\{C\d+\}")
_SENT_BOUNDARY_RE = re.compile(r"(?<=[。．.!！？?])(?:\s+|$)")

def _make_cites_from_hits(hits: List[Dict[str, Any]]) -> List[str]:
    cites, seen = [], set()
    for h in hits:
        ch = h.get("chunk") or {}
        doc = ch.get("doc_id") or h.get("doc_id")
        page = ch.get("page") or h.get("page")
        if doc and page is not None:
            key = (doc, int(page))
            if key in seen: continue
            seen.add(key)
            cites.append(f"[{doc} p.{int(page)}]")
    return cites

def _freeze_citations(text: str):
    """把已存在的 [doc p.#] 凍結為 {Ck}，避免切句時被破壞。"""
    idx = 0
    mapping = {}
    def repl(m):
        nonlocal idx
        token = f"{{C{idx}}}"
        mapping[token] = m.group(0)
        idx += 1
        return token
    frozen = _ANY_CITE_RE.sub(repl, text)
    return frozen, mapping


def _restore_citations(text: str, mapping: Dict[str, str]):
    """把 {Ck} 還原成原 citation。"""
    def repl(m):
        tok = m.group(0)
        return mapping.get(tok, tok)
    return _TOKEN_RE.sub(repl, text)

def _split_sentences_safely(line: str) -> List[str]:
    """只在句末標點（含全形）後切；若無標點則整行視為一句。"""
    line = line.strip()
    if not line:
        return []
    parts = _SENT_BOUNDARY_RE.split(line)
    out = [p.strip() for p in parts if p and p.strip()]
    return out if out else [line]

def _dedup_trailing_citations(sent: str) -> str:
    """句中 citation 去重，只保留最後一個並移到句尾；清掉句尾多餘符號與空白。"""
    tokens = list(_TOKEN_RE.finditer(sent))
    brackets = list(_ANY_CITE_RE.finditer(sent))
    last = None
    if tokens and brackets:
        last = tokens[-1].group(0) if tokens[-1].end() > brackets[-1].end() else brackets[-1].group(0)
    elif tokens:
        last = tokens[-1].group(0)
    elif brackets:
        last = brackets[-1].group(0)
    if last:
        body = _TOKEN_RE.sub("", _ANY_CITE_RE.sub("", sent)).rstrip(" \t，,;；")
        return f"{body} {last}".rstrip()
    return sent.rstrip()

def _replace_non_citation_brackets(text: str) -> str:
    """把非 citation 的 [ ... ] 改為（ ... ）以免干擾評分。"""
    def repl(m):
        inner = m.group(1)
        if re.search(r"\.(?:pdf|md|mdx)\s+p\.\s*\d+", inner, flags=re.I):
            return m.group(0)  # 合法 citation 原樣保留
        return f"（{inner}）"
    # 只處理單層方括號，避免破壞 {Ck}
    return re.sub(r"\[([^\[\]]+)\]", repl, text)

def _ensure_full_citations(answer: str, hits: List[Dict[str, Any]]) -> str:
    """
    逐行/逐句補掛 citation：
    - 標題/表格/條列行整行視為一句；一般行用句末標點切句
    - 已有 citation：只留最後一個並移到句尾；沒有 citation：循環使用 hits 來源補上
    - 全文收尾 trim；確保真正句尾是 ']'
    """
    if not isinstance(answer, str) or not answer.strip():
        return answer

    frozen_text, mapping = _freeze_citations(answer)
    lines = frozen_text.splitlines()
    pool = _make_cites_from_hits(hits)
    if not pool:
        return _restore_citations(frozen_text, mapping)

    out_lines: List[str] = []
    idx = 0
    def pick():
        nonlocal idx
        c = pool[idx % len(pool)]
        idx += 1
        return c

    last_cite: Optional[str] = None

    for line in lines:
        raw = line.rstrip()
        if not raw.strip():
            out_lines.append(raw)
            continue

        is_special = _HEADING_RE.match(raw) or _TABLE_RE.match(raw) or _BULLET_RE.match(raw)
        if is_special:
            if _TOKEN_RE.search(raw) or _ANY_CITE_RE.search(raw) or _LAST_CITE_AT_END_RE.search(_restore_citations(raw, mapping)):
                fixed = _dedup_trailing_citations(raw)
            else:
                use = last_cite or pick()
                fixed = f"{raw} {use}"
                last_cite = use
            out_lines.append(fixed.rstrip())
            continue

        sents = _split_sentences_safely(raw)
        fixed_sents: List[str] = []
        for s in sents:
            s = s.strip()
            if not s:
                continue
            if _TOKEN_RE.search(s) or _ANY_CITE_RE.search(s):
                s2 = _dedup_trailing_citations(s)
                fixed_sents.append(s2)
            else:
                use = last_cite or pick()
                fixed_sents.append(f"{s} {use}")
                last_cite = use
        out_lines.append(" ".join(fixed_sents).rstrip())

    return _restore_citations("\n".join(out_lines), mapping).rstrip()


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    m = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", text, flags=re.I)
    if not m: m = re.search(r"(\[[\s\S]*?\])", text)
    payload = m.group(1) if m else text
    try:
        data = json.loads(payload)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _auto_cite(answer: str, hits: List[Dict[str, Any]]) -> str:
    if _CITE_RE.search(answer or ""):
        return answer or ""
    cites = []
    for h in hits[:2]:
        ch = h.get("chunk") or {}
        doc = ch.get("doc_id") or h.get("doc_id")
        page = ch.get("page") or h.get("page")
        if doc and page is not None:
            cites.append(f"[{doc} p.{int(page)}]")
    if cites:
        return (answer or "").rstrip() + "\n\n來源：" + "，".join(cites)
    return answer or ""


@tool
def initial_search(topic: str) -> str:
    """廣泛搜索，回傳候選頁面（同義詞展開；md/mdx 輕加權；同分以 seed 打散）。"""
    rl = get_run_logger()
    with rl.tool_exec(agent="ME", tool="initial_search", task_id=os.getenv("TASK_ID"), args={"topic": topic}) as _t:
        pass  # 只計時

    global DOC_INDEX
    if DOC_INDEX is None:
        return json.dumps({"status": "error", "error": "index_not_initialized"}, ensure_ascii=False)

    mode = "hybrid"
    m = re.match(r"\s*\[(md_first|pdf_first|hybrid)\]\s*(.*)$", topic, flags=re.I)
    if m:
        mode = m.group(1).lower()
        topic = m.group(2)

    quotas = {"hybrid": (4,4), "md_first": (6,2), "pdf_first": (2,6)}
    q_md, q_pdf = quotas.get(mode, (4,4))
    K = q_md + q_pdf

    def _ext(did: str) -> str:
        return (did or "").rsplit(".", 1)[-1].lower()

    seen, pool = set(), []
    for q in _syn_expand(topic):
        for h in DOC_INDEX.search(q, k=8):
            key = (h.get("doc_id"), int(h.get("page", 0)))
            if key in seen:
                continue
            seen.add(key)
            base = float(h.get("score", 0.0))
            bonus = 0.15 if _ext(h.get("doc_id","")) in ("md","mdx") else 0.0
            h["_boosted"] = base + bonus
            pool.append(h)

    md  = [h for h in pool if _ext(h.get("doc_id","")) in ("md","mdx")]
    pdf = [h for h in pool if _ext(h.get("doc_id","")) == "pdf"]
    oth = [h for h in pool if h not in md and h not in pdf]

    # ★ 用 seed 做穩定 tie-break（同分時隨機但可重現）
    rng = random.Random(get_seed())
    md.sort(key=lambda x: (-x.get("_boosted", 0.0), rng.random()))
    pdf.sort(key=lambda x: (-x.get("_boosted", 0.0), rng.random()))
    oth.sort(key=lambda x: (-x.get("_boosted", 0.0), rng.random()))

    out = md[:q_md] + pdf[:q_pdf]
    if len(out) < K:
        rest = [h for h in md[q_md:] + pdf[q_pdf:] + oth if h not in out]
        # 同樣用 seed 做 tie-break
        rest.sort(key=lambda x: (-x.get("_boosted", 0.0), rng.random()))
        out += rest[: K - len(out)]

    _t.ok(True)
    return json.dumps({"status": "ok", "candidates": out[:K], "mode": mode}, ensure_ascii=False)

@tool
def read_document_chunk(doc_id: str, page: int) -> str:
    """讀取指定頁面全文。"""
    global DOC_INDEX
    if DOC_INDEX is None:
        return json.dumps({"status": "error", "error": "index_not_initialized"}, ensure_ascii=False)
    try:
        chunk = read_chunk(DOC_INDEX, doc_id, int(page))
    except Exception as e:
        return json.dumps({"status": "error", "error": f"read_chunk_failed: {e}"}, ensure_ascii=False)
    return json.dumps({"status": "ok", "chunk": chunk}, ensure_ascii=False)


@tool
def synthesize_and_cite(question: str, hits: List[Dict[str, Any]]) -> str:
    """依 hits 綜合回答；先 Rerank，再合成；必要時 auto-cite 與逐句補掛引用。"""
    # ---- 永遠先給預設 envelope，避免 UnboundLocalError ----
    rl = get_run_logger()
    with rl.tool_exec(agent="ME", tool="synthesize_and_cite", task_id=os.getenv("TASK_ID"),
                      args={"hits": len(hits or [])}) as _t:
        pass

    env = {"answer": "", "coverage": None, "verdict": None, "source": "synthesize_and_cite"}

    def safe_return(answer_text: str, used_idx: List[int]) -> str:
        env["answer"] = answer_text or ""
        try:
            return json.dumps(
                {"status": "ok", "cited_answer": env["answer"], "used_hits": used_idx, "envelope": env},
                ensure_ascii=False
            )
        except Exception:
            return json.dumps(
                {"status": "ok", "cited_answer": env["answer"], "used_hits": used_idx, "envelope": {"answer": env["answer"]}},
                ensure_ascii=False
            )

    # ---- hits 為空：直接回覆 ----
    if not hits:
        _t.ok(True)
        return safe_return("根據提供的文件，未找到相關資訊。", [])

    # ---- Rerank ----
    try:
        rerank_prompt = f"""請評估下列 hits 與問題的相關性，輸出 JSON 陣列：
[{{"index":0,"score":0.9,"reason":"..."}}, ...]
問題：{question}
hits：
{json.dumps(hits, ensure_ascii=False, indent=2)}
"""
        raw = llm.invoke(rerank_prompt)
        arr = _extract_json_array(getattr(raw, "content", "[]"))
    except Exception:
        arr = []

    chosen_idx = [
        r.get("index") for r in arr
        if isinstance(r, dict) and isinstance(r.get("index"), int)
           and 0 <= r["index"] < len(hits) and float(r.get("score", 0)) >= 0.2
    ]
    if not chosen_idx:
        chosen_idx = list(range(min(2, len(hits))))
    chosen = [hits[i] for i in chosen_idx]

    # ---- 建立帶頁碼的 evidence context ----
    ctx = []
    for h in chosen:
        ch = h.get("chunk") or {}
        text = ch.get("text") or h.get("text") or ""
        doc  = ch.get("doc_id") or h.get("doc_id") or "unknown.pdf"
        page = ch.get("page")   or h.get("page")   or -1
        ctx.append(f"[{doc} p.{int(page)}]\n{text}")
    context = "\n\n".join(ctx)

    # ---- 合成（把 seed 傳給 LLM，如 llm 支援 with_config/seed）----
    sys = ("你是 TEP 助理；只根據證據回答。若資訊有限，也要給出最接近的結論。"
           "每一句（包含條列行）都要在句尾附上 [檔名 p.頁碼]。")
    human = f"問題：\n{question}\n\n證據（已含頁碼）：\n{context}\n"

    try:
        llm_seeded = llm.with_config({"seed": get_seed()}) if hasattr(llm, "with_config") else llm
    except Exception:
        llm_seeded = llm

    try:
        out = (ChatPromptTemplate.from_messages([
                SystemMessage(content=sys),
                HumanMessage(content=human)
            ]) | llm_seeded).invoke({})
        answer = getattr(out, "content", "") or ""
    except Exception:
        answer = "根據提供的文件，未找到相關資訊。"

    # 若模型仍說「未找到」，用 hits 摘要兜底
    if ("未找到" in answer) and chosen:
        lines = []
        for h in chosen[:2]:
            ch = h.get("chunk") or {}
            doc = ch.get("doc_id") or h.get("doc_id")
            page = ch.get("page") or h.get("page")
            first_line = (ch.get("text") or "").strip().splitlines()
            first_line = next((s for s in first_line if s.strip()), "")
            lines.append(f"依據 [{doc} p.{int(page)}]：{first_line}")
        answer = "綜合可得：\n" + "\n".join(lines)

    # ---- 引用後處理：先全局兜底，再逐句/逐行補掛 ----
    try:
        answer = _auto_cite(answer, chosen)
        answer = _replace_non_citation_brackets(answer)
        answer = _ensure_full_citations(answer, chosen)
    except Exception:
        pass
    try:
        answer = _ensure_full_citations(answer, chosen)
    except Exception:
        pass

    _t.ok(True)
    return safe_return(answer, chosen_idx)


@tool
def search_and_answer(question: str) -> str:
    """Baseline：搜尋並回傳最相關頁面的全文（不綜合）。"""
    global DOC_INDEX
    if DOC_INDEX is None:
        return json.dumps({"status": "error", "error": "index_not_initialized"}, ensure_ascii=False)
    hits = DOC_INDEX.search(question, k=6)
    chunks = [read_chunk(DOC_INDEX, h["doc_id"], h["page"]) for h in hits]
    return json.dumps({"status": "ok", "hits": chunks}, ensure_ascii=False)


class SimpleTool:
    """把純函式包成有 .name 的可呼叫物件"""
    def __init__(self, func: Callable, name: str | None = None, description: str = "") -> None:
        self.func = func
        self.name = name or getattr(func, "name", None) or getattr(func, "__name__", "tool")
        self.description = description

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)

def normalize_tools(tools: List[Any]) -> List[Any]:
    """確保工具陣列中的每一項都有 .name 與可呼叫性"""
    norm = []
    for t in tools:
        if hasattr(t, "name") and callable(getattr(t, "__call__", None)):
            norm.append(t)
        elif callable(t):  # 純函式 → 包裝
            norm.append(SimpleTool(t))
        else:
            raise TypeError(f"Tool {t} is neither callable nor has .name")
    return norm


@tool("kg_query_fault")
def kg_query_fault(fault_id: int) -> str:
    """Query TEP fault knowledge for a specific IDV fault (0-20).

    Returns structured fault knowledge: description, diagnostic sensors, affected process units.
    Use this BEFORE PDF search for fault identification — faster and more structured.

    Args:
        fault_id: Integer fault ID (e.g. 4 for reactor cooling water fault).

    Returns:
        JSON with fault description, diagnostic_sensors list, and process unit context.
    """
    from tep_knowledge import lookup_fault
    result = lookup_fault(fault_id)
    return json.dumps(result, ensure_ascii=False)


def get_me_tools(mode: str):

    tools = [initial_search, read_document_chunk, synthesize_and_cite,
             me_warmup_read, me_write_fact, kg_query_fault]

    # 保險檢查：每個工具都應該是 LangChain Tool 物件（具有 .name）
    assert all(hasattr(t, "name") for t in tools), "Some ME tools are not LangChain Tool objects."
    tool_map = {t.name: t for t in tools}
    return tools, tool_map

