from sqlalchemy import create_engine, text

def check_database():
    """Quick check to see what data is available"""
    
    print("\n🔍 Checking bms_ged database...")
    print("=" * 60)
    
    try:
        engine = create_engine("mysql+pymysql://root@172.23.208.1:3306/bms_ged")
        
        with engine.connect() as conn:
            # Total complaints
            total = conn.execute(text("SELECT COUNT(*) FROM complains")).scalar()
            print(f"📊 Total complaints: {total}")
            
            # By status
            statuses = conn.execute(text("""
                SELECT compl_job_status, COUNT(*) as count
                FROM complains
                GROUP BY compl_job_status
            """)).fetchall()
            
            print(f"\n📋 By Status:")
            status_names = {0: "Pending", 1: "In Progress", 2: "Resolved"}
            for row in statuses:
                status_name = status_names.get(row.compl_job_status, "Unknown")
                print(f"   {status_name} (status={row.compl_job_status}): {row.count}")
            
            # Resolved with solutions
            resolved_with_solution = conn.execute(text("""
                SELECT COUNT(*) 
                FROM complains 
                WHERE compl_job_status = 2 
                AND compl_solution IS NOT NULL 
                AND compl_solution != ''
                AND compl_solution != 'NULL'
            """)).scalar()
            
            print(f"\n✅ Resolved complaints WITH solution: {resolved_with_solution}")
            print(f"   (These will be loaded into RAG)")
            
            # Sample resolved
            if resolved_with_solution > 0:
                samples = conn.execute(text("""
                    SELECT compl_id, compl_title, compl_type, compl_solution
                    FROM complains
                    WHERE compl_job_status = 2
                    AND compl_solution IS NOT NULL
                    AND compl_solution != ''
                    AND compl_solution != 'NULL'
                    ORDER BY compl_id DESC
                    LIMIT 3
                """)).fetchall()
                
                print(f"\n📝 Sample resolved complaints:")
                print("-" * 60)
                for row in samples:
                    print(f"   ID {row.compl_id}: {row.compl_title}")
                    print(f"      Type: {row.compl_type}")
                    solution = row.compl_solution[:80] if row.compl_solution else "No solution"
                    print(f"      Solution: {solution}...")
                    print()
        
        print("=" * 60)
        print("✅ Database check complete!\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database()