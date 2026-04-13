from core.external_retriever import ExternalDocument, external_retriever

doc = ExternalDocument(
      doc_id="news-nvda-001",
      ticker="NVDA",
      title="NVIDIA raises guidance",
      text="NVIDIA said it raised full-year guidance on strong data center demand.",
      published_at=1741826900,
      source_type="news",
      url="https://example.com/news/nvda-001",
      importance=0.8,
      metadata={"publisher": "example"},
  )

external_retriever.reset_backend()
external_retriever.upsert_documents([doc])
print(external_retriever.get_stats())
external_retriever.reset_backend()