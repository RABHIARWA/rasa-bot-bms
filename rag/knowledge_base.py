import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import List, Dict
import uuid

class ComplaintKnowledgeBase:
    def __init__(self, persist_directory="./chroma_db"):
        """Initialize ChromaDB for storing complaint knowledge"""
        
        # Initialize ChromaDB client with persistence
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Create or get collection
        self.collection = self.client.get_or_create_collection(
            name="complaint_solutions",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Use embedding model to convert text to vectors
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        print(f"✅ ChromaDB initialized at: {persist_directory}")
        print(f"✅ Collection 'complaint_solutions' ready")
        
    def add_complaint(self, title: str, description: str, complaint_id: int, 
                     complaint_type: str, solution: str, status: str = "resolved"):
        """Add a resolved complaint to the knowledge base"""
        
        # Combine all text for better semantic search
        combined_text = f"Type: {complaint_type}\nTitle: {title}\nDescription: {description}\nSolution: {solution}"
        
        # Generate embedding (convert text to vector)
        embedding = self.embedding_model.encode(combined_text).tolist()
        
        # Store in ChromaDB
        try:
            self.collection.add(
                documents=[combined_text],
                embeddings=[embedding],
                metadatas=[{
                    "complaint_id": complaint_id,
                    "title": title,
                    "description": description,
                    "complaint_type": complaint_type,
                    "solution": solution,
                    "status": status
                }],
                ids=[f"complaint_{complaint_id}_{uuid.uuid4().hex[:8]}"]
            )
            print(f"✅ Added complaint {complaint_id} to knowledge base")
        except Exception as e:
            print(f"❌ Error adding complaint {complaint_id}: {e}")
    
    def search_similar_complaints(self, query: str, complaint_type: str = None, top_k: int = 3) -> List[Dict]:
        """Search for similar past complaints using semantic search"""
        
        # Generate query embedding
        query_embedding = self.embedding_model.encode(query).tolist()
        
        # Build where filter for complaint type
        where_filter = None
        if complaint_type:
            where_filter = {"complaint_type": complaint_type}
        
        # Search in ChromaDB
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter
            )
            
            # Format results
            similar_complaints = []
            if results['metadatas'] and len(results['metadatas'][0]) > 0:
                for i, metadata in enumerate(results['metadatas'][0]):
                    # Calculate similarity score (1 - distance)
                    similarity = 1 - results['distances'][0][i] if results['distances'] else 0
                    
                    similar_complaints.append({
                        "complaint_id": metadata.get("complaint_id"),
                        "title": metadata.get("title"),
                        "description": metadata.get("description"),
                        "type": metadata.get("complaint_type"),
                        "solution": metadata.get("solution"),
                        "similarity_score": similarity
                    })
            
            print(f"🔍 Found {len(similar_complaints)} similar complaints")
            return similar_complaints
            
        except Exception as e:
            print(f"❌ Search error: {e}")
            return []
    
    def get_stats(self):
        """Get statistics about the knowledge base"""
        try:
            count = self.collection.count()
            return {
                "total_complaints": count,
                "collection_name": self.collection.name
            }
        except Exception as e:
            print(f"❌ Error getting stats: {e}")
            return {}
    
    def clear_all(self):
        """Clear all data from knowledge base (use with caution!)"""
        try:
            self.client.delete_collection(name="complaint_solutions")
            self.collection = self.client.get_or_create_collection(
                name="complaint_solutions",
                metadata={"hnsw:space": "cosine"}
            )
            print("✅ Knowledge base cleared")
        except Exception as e:
            print(f"❌ Error clearing knowledge base: {e}")