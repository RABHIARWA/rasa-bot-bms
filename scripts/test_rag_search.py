import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.knowledge_base import ComplaintKnowledgeBase

def test_specific_query():
    """Test RAG with specific power sag complaint"""
    
    # Your exact query
    query = "Water is running everywhere in the toilet"
    complaint_type = "Plumbing failure"
    
    print("\n" + "="*70)
    print("🧪 TESTING RAG WITH YOUR SPECIFIC QUERY")
    print("="*70)
    print(f"\n📝 Query: {query}")
    print(f"🏷️  Type: {complaint_type}")
    print("-"*70)
    
    # Initialize KB
    kb = ComplaintKnowledgeBase(persist_directory="./chroma_db")
    
    # Check if KB has data
    stats = kb.get_stats()
    total = stats.get('total_complaints', 0)
    print(f"\n📊 ChromaDB Stats:")
    print(f"   Total complaints: {total}")
    
    if total == 0:
        print("\n❌ ERROR: ChromaDB is EMPTY!")
        print("   Run: python scripts/populate_knowledge_base.py")
        return
    
    # Test 1: Search WITHOUT type filter
    print(f"\n{'='*70}")
    print("🔍 TEST 1: Search WITHOUT type filter (all types)")
    print("-"*70)
    
    results_all = kb.search_similar_complaints(
        query=query,
        complaint_type=None,
        top_k=5
    )
    
    if results_all:
        print(f"✅ Found {len(results_all)} similar complaints (any type):\n")
        for i, result in enumerate(results_all, 1):
            similarity = result['similarity_score'] * 100
            print(f"{i}. Similarity: {similarity:.1f}%")
            print(f"   Type: {result['type']}")
            print(f"   Title: {result['title']}")
            print(f"   Description: {result['description'][:80]}...")
            print(f"   Solution: {result['solution'][:80]}...")
            print()
    else:
        print("❌ No similar complaints found!")
    
    # Test 2: Search WITH type filter
    print(f"{'='*70}")
    print(f"🔍 TEST 2: Search WITH type filter = '{complaint_type}'")
    print("-"*70)
    
    results_filtered = kb.search_similar_complaints(
        query=query,
        complaint_type=complaint_type,
        top_k=5
    )
    
    if results_filtered:
        print(f"✅ Found {len(results_filtered)} similar complaints (filtered by type):\n")
        for i, result in enumerate(results_filtered, 1):
            similarity = result['similarity_score'] * 100
            print(f"{i}. Similarity: {similarity:.1f}%")
            print(f"   Title: {result['title']}")
            print(f"   Description: {result['description'][:80]}...")
            print(f"   Solution: {result['solution'][:80]}...")
            print()
    else:
        print("❌ No similar complaints found with type filter!")
        print(f"\n💡 Checking what electricity complaints exist in DB...")
        
        # Show what electricity complaints we have
        electricity_results = kb.search_similar_complaints(
            query="electricity power lights outlet",
            complaint_type="Electricity failure",
            top_k=10
        )
        
        if electricity_results:
            print(f"\n📋 Available electricity complaints in DB:")
            for i, r in enumerate(electricity_results, 1):
                print(f"   {i}. {r['title']}")
        else:
            print("\n⚠️  No 'Electricity failure' complaints in database at all!")
    
    # Generate solution preview
    print(f"\n{'='*70}")
    print("💡 SOLUTION GENERATION PREVIEW")
    print("-"*70)
    
    if results_filtered or results_all:
        best_results = results_filtered if results_filtered else results_all
        
        print(f"\n✅ RAG would use these {len(best_results[:3])} complaints:\n")
        for i, r in enumerate(best_results[:3], 1):
            sim = r['similarity_score'] * 100
            print(f"{i}. [{sim:.1f}% match] {r['title']}")
            print(f"   Solution: {r['solution']}")
            print()
        
        print("🤖 GPT would receive this context:")
        print("-"*70)
        context = "Similar past cases from your building:\n\n"
        for i, comp in enumerate(best_results[:3], 1):
            similarity = comp['similarity_score'] * 100
            context += f"Case {i} (Similarity: {similarity:.0f}%):\n"
            context += f"  Problem: {comp['description']}\n"
            context += f"  Solution: {comp['solution']}\n\n"
        print(context)
        
    else:
        print("\n❌ No similar cases found - GPT would generate generic solution")
    
    print("="*70 + "\n")

if __name__ == "__main__":
    test_specific_query()