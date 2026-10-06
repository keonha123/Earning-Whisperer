"""직전 콜 핵심 문장 저장소.

트랜스크립트 컬렉션을 함께 쓰되 `store="transcript_statement"` 로 구분한다. 기존
트랜스크립트 조회(`find_latest_transcript` · `search_prior_transcript_chunks`)는
`store="transcript"` 로 거르므로 이 문장들이 섞여 들어가지 않는다.

**벡터는 의미가 없는 고정값이다.** 대조는 한 콜의 문장 전체를 꺼내 쓰므로 검색하지 않는다.
컬렉션이 벡터를 요구해서 넣을 뿐이고, 그래서 임베딩 API 를 부르지 않는다(콜 1건에 약 60요청과
무료 등급 배치 간격 대기가 사라진다). payload 의 `embedding_provider="none"` 이 그 표시다.
`store` 로 걸러 조회하므로 같은 컬렉션의 트랜스크립트 검색에 섞이지 않는다. 나중에 문장 검색이
필요해지면 실제 임베딩으로 다시 넣는다.

동시 적재: 한 프로세스 안에서는 `replace` 가 이벤트 루프를 붙잡은 채 삭제와 저장을 끝내므로
요청끼리 섞이지 않는다. 워커를 여럿 두거나 이 호출을 스레드로 옮기면 두 요청의 문장이 섞일 수 있다.
"""

from __future__ import annotations

from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

try:
    from models.transcript_statement_models import KeyStatement
except ImportError:  # pragma: no cover
    from ..models.transcript_statement_models import KeyStatement


STATEMENT_STORE = "transcript_statement"
_SCROLL_PAGE = 256


def _point_id(statement_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"earningwhisperer:transcript-statement:{statement_id}"))


class QdrantTranscriptStatementRepository:
    def __init__(self, *, client: Any, collection_name: str, vector_size: int) -> None:
        self.client = client
        self.collection_name = collection_name
        # 길이 1 의 고정 벡터. 영벡터는 코사인 거리에서 정의되지 않아 쓰지 않는다.
        self._placeholder_vector = [1.0] + [0.0] * (vector_size - 1)

    @classmethod
    def sharing(cls, transcript_repository: Any) -> "QdrantTranscriptStatementRepository":
        """트랜스크립트 저장소와 같은 클라이언트 · 컬렉션을 쓴다."""
        return cls(
            client=transcript_repository.client,
            collection_name=transcript_repository.collection_name,
            vector_size=transcript_repository.embedding_dimension,
        )

    def replace(self, document_id: str, statements: Sequence[KeyStatement]) -> int:
        """해당 콜의 문장을 모두 지우고 새로 넣는다.

        다시 추출하면 문장 구성이 달라지므로 덮어쓰기로는 옛 문장이 남는다.
        """
        from qdrant_client import models

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(filter=self._document_filter(document_id)),
        )
        if not statements:
            return 0
        points = [
            models.PointStruct(
                id=_point_id(s.statement_id),
                vector=self._placeholder_vector,
                payload={**s.model_dump(mode="json"), "store": STATEMENT_STORE, "embedding_provider": "none"},
            )
            for s in statements
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    def list(self, document_id: str) -> list[KeyStatement]:
        """해당 콜의 문장 전체를 콜 안의 순서대로 돌려준다."""
        statements: list[KeyStatement] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=self._document_filter(document_id),
                limit=_SCROLL_PAGE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            statements.extend(KeyStatement.model_validate(point.payload) for point in points)
            if offset is None:
                break
        return sorted(statements, key=lambda s: s.order)

    @staticmethod
    def _document_filter(document_id: str) -> Any:
        from qdrant_client import models

        return models.Filter(
            must=[
                models.FieldCondition(key="store", match=models.MatchValue(value=STATEMENT_STORE)),
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
            ]
        )


class InMemoryTranscriptStatementRepository:
    """Qdrant 를 쓰지 않을 때(VECTOR_STORE_BACKEND=memory)의 저장소. 프로세스가 끝나면 사라진다."""

    def __init__(self) -> None:
        self._by_document: dict[str, list[KeyStatement]] = {}

    def replace(self, document_id: str, statements: Sequence[KeyStatement]) -> int:
        self._by_document[document_id] = list(statements)
        return len(statements)

    def list(self, document_id: str) -> list[KeyStatement]:
        return sorted(self._by_document.get(document_id, []), key=lambda s: s.order)


__all__ = ["InMemoryTranscriptStatementRepository", "QdrantTranscriptStatementRepository", "STATEMENT_STORE"]
