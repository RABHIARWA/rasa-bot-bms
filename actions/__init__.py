"""Pre-load RAG on startup"""

print("🔄 Pre-warming RAG system...")

try:
    import sys
    import os
    from pathlib import Path
    
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    from rag.knowledge_base import ComplaintKnowledgeBase
    
    # Initialize KB on startup (not on first request)
    kb = ComplaintKnowledgeBase(persist_directory="./chroma_db")
    print("✅ RAG system pre-warmed and ready!")
    
except Exception as e:
    print(f"⚠️ RAG pre-warm failed: {e}")