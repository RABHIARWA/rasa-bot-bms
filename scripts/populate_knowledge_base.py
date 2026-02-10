import sys
import os

# Add parent directory to path so we can import from rag module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.knowledge_base import ComplaintKnowledgeBase
from sqlalchemy import create_engine, text


# --- DB CONFIG FROM ENV ---
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_DATABASE = os.getenv("DB_DATABASE", "bms_ged")
DB_USERNAME = os.getenv("DB_USERNAME", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")   # default you mentioned


def get_db_engine():
    url = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"
    print(f"📡 Connecting to database: {DB_HOST}:{DB_PORT}/{DB_DATABASE} as {DB_USERNAME}")
    return create_engine(url)


def populate_from_database():
    """
    Load resolved complaints from bms_ged database
    Only loads complaints where compl_job_status = 2 (resolved)
    """
    
    print("\n" + "="*70)
    print("🚀 POPULATING RAG KNOWLEDGE BASE FROM DATABASE")
    print("="*70)
    print(f"Database: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
    print("Filter: compl_job_status = 2 (Resolved)")
    print("="*70 + "\n")
    
    # Initialize ChromaDB knowledge base
    kb = ComplaintKnowledgeBase(persist_directory="./chroma_db")
    
    try:
        # Connect to YOUR database
        print("📡 Connecting to database...")
        engine = get_db_engine()
        
        # Query to get resolved complaints with solutions
        query = text("""
            SELECT 
                compl_id,
                compl_title,
                compl_description,
                compl_type,
                compl_solution,
                compl_job_status,
                updated_at
            FROM complains
            WHERE compl_job_status = 2
              AND compl_solution IS NOT NULL 
              AND compl_solution != ''
              AND compl_solution != 'NULL'
            ORDER BY compl_id DESC
        """)
        
        print("🔍 Executing query...\n")
        
        with engine.connect() as conn:
            results = conn.execute(query).fetchall()
        
        total_found = len(results)
        print(f"✅ Found {total_found} resolved complaints with solutions\n")
        
        if total_found == 0:
            print("⚠️  No resolved complaints found!")
            print("\nPossible reasons:")
            print("1. No complaints have compl_job_status = 2")
            print("2. No complaints have solutions yet")
            print("3. All solutions are empty/NULL")
            print("\nTry this SQL to check:")
            print("   SELECT COUNT(*) FROM complains WHERE compl_job_status = 2;")
            print("   SELECT COUNT(*) FROM complains WHERE compl_job_status = 2 AND compl_solution IS NOT NULL;")
            return
        
        print("-"*70)
        print("📝 Adding complaints to ChromaDB vector database...")
        print("-"*70 + "\n")
        
        # Add each complaint to RAG
        count = 0
        errors = 0
        
        for row in results:
            try:
                complaint_id = str(row.compl_id)
                title = row.compl_title or "No title"
                description = row.compl_description or "No description"
                complaint_type = row.compl_type or "Unknown"
                solution = row.compl_solution or "No solution"
                
                # Add to RAG
                kb.add_complaint(
                    complaint_id=complaint_id,
                    title=title,
                    description=description,
                    complaint_type=complaint_type,
                    solution=solution,
                    status="resolved"
                )
                count += 1
                
                # Show progress every 10 complaints
                if count % 10 == 0:
                    print(f"   ✓ Processed {count}/{total_found} complaints...")
                    
            except Exception as e:
                errors += 1
                print(f"   ✗ Error with complaint {row.compl_id}: {e}")
        
        # Final statistics
        print("\n" + "="*70)
        print("📊 FINAL STATISTICS")
        print("="*70)
        
        stats = kb.get_stats()
        print(f"Total complaints in database: {total_found}")
        print(f"Successfully added to RAG: {count}")
        if errors > 0:
            print(f"Errors encountered: {errors}")
        print(f"Knowledge base total: {stats.get('total_complaints', 0)}")
        print(f"Collection: {stats.get('collection_name', 'N/A')}")
        print("="*70)
        
        # Show some examples
        if count > 0:
            print(f"\n📋 SAMPLE COMPLAINTS LOADED:")
            print("-"*70)
            sample_results = results[:3]  # Show first 3
            for row in sample_results:
                print(f"\n   ID: {row.compl_id}")
                print(f"   Title: {row.compl_title}")
                print(f"   Type: {row.compl_type}")
                solution_preview = row.compl_solution[:80] if row.compl_solution else "No solution"
                print(f"   Solution: {solution_preview}...")
        
        print("\n" + "="*70)
        print("✅ POPULATION COMPLETE!")
        print("="*70)
        print("\n🎯 Next steps:")
        print("   1. Run: rasa train")
        print("   2. Run: rasa run actions")
        print("   3. Run: rasa shell")
        print("   4. Test with: 'I have a complaint about water pressure'\n")
        
    except Exception as e:
        print("\n" + "="*70)
        print("❌ ERROR")
        print("="*70)
        print(f"Error: {e}\n")
        print("Please verify:")
        print(f"✓ MySQL server is running at {DB_HOST}:{DB_PORT}")
        print(f"✓ Database '{DB_DATABASE}' exists")
        print(f"✓ User '{DB_USERNAME}' has access")
        print("✓ Table 'complains' exists")
        print("✓ Columns: compl_id, compl_title, compl_description, compl_type, compl_solution, compl_job_status")
        print("\nFull error details:")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║          RAG KNOWLEDGE BASE POPULATION SCRIPT                      ║")
    print("║          Loading complaints from bms_ged database                  ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print("\n")
    
    populate_from_database()
    
    print("\n")
