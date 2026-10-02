# Embedding compatibility and collection migration

## Current upstream-compatible policy
Embedding compatibility is controlled by collection configuration, not a per-point embedding_version query filter. This matches main6a2cdfc / PR133c047a6e. Legacy points without version metadata remain searchable when they belong to the correctly configured collection. embedding_version remains ingestion provenance; it is not permission to relabel vectors.

External evidence uses EXTERNAL_EMBEDDING_* and QDRANT_COLLECTION_NAME. Transcripts use EMBEDDING_* and QDRANT_TRANSCRIPT_COLLECTION_NAME. Reader/writer provider, model and dimension must agree. Provider or dimension configuration errors must be explicit, not silently replaced with a different embedding space.

The current client automatically checks the collection vector dimension. It does not infer the historical embedding model from vectors or enforce a collection-level provider/model manifest. Operators must keep provider/model settings aligned with the collection's ingestion history; equal dimensions alone do not establish semantic compatibility.

## Migration and rollback
1. Retain original source documents, old collection names and complete embedding settings.
2. If provider/model/dimension or chunking changes, populate NEW collections by embedding originals. Never merely change metadata. Do not mix vectors from different models even when dimensions match.
3. Verify document/chunk counts, final transcript turns, representative search/diff results and unchanged news coverage before cutover. Test the intended real embedding provider.
4. Switch readers and writers together; retain old collections for rollback. No automatic purge/deletion of live data.

The local-only tools/reindex_transcripts.py previews by default, refuses an existing destination on --apply, and verifies stored chunk counts. It is not a production-server migration tool. data_pipeline/tools/demo/ingest_demo_transcript.py can call a configured engine; do not use --purge against a live collection as a migration strategy.

No production collection was modified in this task. Existing homogeneous legacy collections remain compatible; changing the embedding model still requires reindexing. This supersedes the September30 local candidate's stricter per-point-filter proposal.
