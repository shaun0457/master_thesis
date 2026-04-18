# agents/me.py
"""
Machine Expert (ME) Agent with RAG integration.
Provides domain knowledge from TEP documentation.
"""

from .base import BaseAgent
from mas.tools import RAGEngine


class MachineExpertAgent(BaseAgent):
    """
    Machine Expert agent with RAG-powered documentation search.

    Capabilities:
    - Domain knowledge from TEP documentation via RAG engine
    - Semantic search over TEP_docs/
    - Peer judging for DE and DS from machine perspective
    """

    def __init__(self, bb_store, router, **kwargs):
        """
        Initialize Machine Expert with RAG engine.

        Args:
            bb_store: BlackboardStore instance
            router: Router instance
            **kwargs: Additional args passed to BaseAgent
        """
        super().__init__("me", bb_store, router, **kwargs)

        # Initialize RAG engine
        try:
            self.rag = RAGEngine()
            self.rag_enabled = True
            stats = self.rag.get_stats()
            print(f"[ME] [OK] RAG engine initialized: {stats['total_chunks']} chunks ready")
        except Exception as e:
            self.rag = None
            self.rag_enabled = False
            print(f"[ME] [WARN]  RAG engine not available: {e}")

    def _build_prompt(self, context: dict) -> str:
        """
        Build prompt with RAG-augmented context.

        Args:
            context: Run context dict

        Returns:
            str: Enhanced prompt with relevant documentation
        """
        # Get base prompt from parent
        base_prompt = super()._build_prompt(context)

        # Extract task keywords for RAG query
        task = context.get('task', '')
        query = context.get('query', '')
        combined_text = f"{task} {query}"

        # Query RAG for relevant documentation
        rag_context = ""
        if self.rag_enabled and combined_text.strip():
            try:
                results = self.rag.query(combined_text, top_k=3)
                if results:
                    rag_context = "\n\n# Relevant TEP Documentation (from RAG)\n"
                    for i, result in enumerate(results):
                        rag_context += f"\n## [{result['source']}] (relevance: {result['score']:.3f})\n"
                        rag_context += f"{result['text']}\n"

                    print(f"[ME] [OK] RAG found {len(results)} relevant docs")
            except Exception as e:
                print(f"[ME] [WARN]  RAG query failed: {e}")

        # Combine base prompt with RAG context
        return base_prompt + rag_context
