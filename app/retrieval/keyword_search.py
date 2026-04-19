from langchain_community.retrievers import BM25Retriever


class KeywordRetriever:
    def __init__(self, documents):
        self.retriever = BM25Retriever.from_documents(documents, bm25_variant="plus",
    bm25_params={"delta": 0.5})

    def search(self, query):
        return self.retriever.invoke(query)