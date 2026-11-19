"""문서로 챗봇 만들기: 지식베이스 하나를 골라 '문서에서 찾아 답하는 챗봇'을 한 번에 만든다."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.models import App, KnowledgeBase
from api.services import apps as app_svc
from api.services.app_config import merged_features


def doc_bot_graph(kb_id: str, kb_name: str) -> dict[str, Any]:
    """질문 받기 → 문서 찾기 → 답 쓰기 → 답 보여 주기"""
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "질문 받기",
                    "fields": [
                        {"key": "message", "label": "질문", "type": "text", "required": True}
                    ],
                },
            },
            {
                "id": "n2",
                "type": "knowledge_search",
                "position": {"x": 300, "y": 0},
                "data": {
                    "label": f"'{kb_name}'에서 찾기"[:40],
                    "kb_id": kb_id,
                    "query": "{{n1.message}}",
                    "top_k": 4,
                },
            },
            {
                "id": "n3",
                "type": "llm",
                "position": {"x": 600, "y": 0},
                "data": {
                    "label": "답 쓰기",
                    "provider": "default",
                    "temperature": 0.2,
                    "system": (
                        "당신은 올려 둔 문서로 답하는 도우미예요. 아래 자료에 있는 내용만으로 짧고 "
                        "정확하게 답하고, 자료에 없으면 '문서에서 찾지 못했어요. 담당자에게 문의해 "
                        "주세요.'라고 답하세요."
                    ),
                    "prompt": "자료:\n{{n2.context}}\n\n질문: {{n1.message}}",
                    "memory": True,
                },
            },
            {
                "id": "n4",
                "type": "output",
                "position": {"x": 900, "y": 0},
                "data": {"label": "답", "template": "{{n3.text}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n3", "target": "n4"},
        ],
        "variables": {},
    }


def create_doc_bot(
    db: Session,
    kb: KnowledgeBase,
    *,
    user_id: str,
    name: str,
    project_id: str | None,
) -> App:
    """챗봇 앱을 만들고 첫 버전까지 저장한다(저장이 안 되면 작업본으로만 둔다)."""
    clean = name.strip() or f"{kb.name} 챗봇"
    graph = doc_bot_graph(kb.id, kb.name)
    app = App(
        workspace_id=kb.workspace_id,
        name=clean,
        slug=app_svc.slugify(clean),
        type="chat",
        description=f"'{kb.name}' 문서로 질문에 답해요.",
        icon="📚",
        status="draft",
        created_by=user_id,
        draft_graph=graph,
        project_id=project_id or kb.project_id,
        features=merged_features(
            {
                "opening_statement": f"'{kb.name}'에 대해 물어보세요. 답에 근거 문서를 함께 보여 드려요.",
                "citations": {"enabled": True},
            }
        ),
    )
    db.add(app)
    db.flush()
    app_svc.save_version(db, app, graph, "문서로 챗봇 만들기", user_id)
    db.flush()
    return app
