from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from langchain.retrievers import EnsembleRetriever
from app.retrieval.keyword_search import KeywordRetriever
from app.retrieval.vector_store import VectorStore

class HybridRetriever:
    def __init__(self, vector_store, keyword_retriever):
        self.vector_store = vector_store.retriever()
        self.keyword_retriever = keyword_retriever
        self.compressor = FlashrankRerank()

    def hybrid_retriever(self):
        hybrid_retriever = EnsembleRetriever(
            retrievers=[self.vector_store, self.keyword_retriever],
            weights=[0.7, 0.3]
        )
        return hybrid_retriever

    def compression_retriever(self):
        return ContextualCompressionRetriever(
            base_compressor=self.compressor, 
            base_retriever=self.hybrid_retriever()
        )

