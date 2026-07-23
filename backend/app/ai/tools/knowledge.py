from app.ai.tools.contracts import (
    CitationOutput,
    KnowledgeSearchInput,
    KnowledgeSearchOutput,
    RuntimeContext,
)
from app.services.knowledge import KnowledgeSearchService


class KnowledgeBaseTool:
    name = "search_knowledge_base"

    def __init__(self, knowledge: KnowledgeSearchService) -> None:
        self.knowledge = knowledge

    async def execute(
        self,
        payload: KnowledgeSearchInput,
        context: RuntimeContext,
    ) -> KnowledgeSearchOutput:
        del context
        result = await self.knowledge.search(
            payload.query,
            category=payload.category,
        )
        return KnowledgeSearchOutput(
            evidence=[item.content for item in result.evidence],
            citations=[CitationOutput.model_validate(citation) for citation in result.citations],
            insufficient=result.insufficient,
            conflict=result.conflict,
            requires_human=result.requires_human,
        )
