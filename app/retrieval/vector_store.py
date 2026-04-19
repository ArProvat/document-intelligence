from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings


class VectorStore:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large",
            dimensions=1024
        )
        self.vector_store = Chroma(
            collection_name="example_collection",
            embedding_function=self.embeddings,
            persist_directory="./chroma_langchain_db", 
            collection_metadata = {
                "hnsw:space": "cosine",
                "hnsw:construction_ef": 100,      
                "hnsw:M": 16                      
            }

        )

    def add_documents(self, documents):
        self.vector_store.add_documents(documents)

    def retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": 10 ,"fetch_k": 20})

    def delete_documents(self, filter=None):
        self.vector_store.delete(filter=filter)

    
    
    