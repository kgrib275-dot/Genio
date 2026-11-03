"""그래프 검증: 순환·참조·필수 노드·분기·병렬·형식·커넥터·지식베이스."""

import copy
from typing import Any

from api.engine.validator import ValidationEnv, validate_graph
from nodes import registry


def env(**kw: Any) -> ValidationEnv:
    return ValidationEnv(registry=registry, **kw)


def base_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {"label": "입력", "fields": [{"key": "message", "required": True}]},
            },
            {
                "id": "n2",
                "type": "llm",
                "data": {
                    "label": "분류",
                    "prompt": "{{n1.message}}",
                    "output_schema": {
                        "type": "object",
                        "properties": {"category": {"type": "string"}},
                    },
                },
            },
            {
                "id": "n3",
                "type": "condition",
                "data": {
                    "cases": [{"id": "c1", "when": "{{n2.category}} == 'billing'"}],
                    "else": "c_else",
                },
            },
            {"id": "n4", "type": "output", "data": {"template": "결제: {{n2.category}}"}},
            {"id": "n5", "type": "output", "data": {"template": "기타: {{n1.message}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n3", "sourceHandle": "c1", "target": "n4"},
            {"id": "e4", "source": "n3", "sourceHandle": "c_else", "target": "n5"},
        ],
        "variables": {},
    }


def messages(result: Any) -> list[str]:
    return [e.message for e in result.errors]


def test_valid_graph_passes() -> None:
    result = validate_graph(base_graph(), env())
    assert result.valid, messages(result)


def test_cycle_detected() -> None:
    g = base_graph()
    g["edges"].append({"id": "e9", "source": "n4", "target": "n2"})
    result = validate_graph(g, env())
    assert not result.valid
    assert any("순환" in m for m in messages(result))


def test_input_count_and_output_required() -> None:
    g = base_graph()
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "output"]
    g["edges"] = [e for e in g["edges"] if e["target"] not in ("n4", "n5")]
    g["nodes"].append({"id": "n6", "type": "input", "data": {"fields": [{"key": "x"}]}})
    msgs = messages(validate_graph(g, env()))
    assert any("입력 노드는 정확히 1개" in m for m in msgs)
    assert any("결과 노드" in m for m in msgs)


def test_missing_reference_and_field() -> None:
    g = base_graph()
    g["nodes"][3]["data"]["template"] = "{{n9.text}} {{n2.nope}}"
    msgs = messages(validate_graph(g, env()))
    assert any("없는 노드 'n9'" in m for m in msgs)
    assert any("'nope' 값이 없어요" in m for m in msgs)


def test_reference_to_later_node_rejected() -> None:
    g = base_graph()
    g["nodes"][1]["data"]["prompt"] = "{{n4.text}}"
    msgs = messages(validate_graph(g, env()))
    assert any("앞에 있지 않아" in m for m in msgs)


def test_required_setting_missing() -> None:
    g = base_graph()
    del g["nodes"][1]["data"]["prompt"]
    result = validate_graph(g, env())
    errs = [e for e in result.errors if e.node_id == "n2"]
    assert errs and errs[0].field == "prompt" and "채워" in errs[0].message


def test_condition_handle_rules() -> None:
    g = copy.deepcopy(base_graph())
    g["edges"][2]["sourceHandle"] = "c9"
    msgs = messages(validate_graph(g, env()))
    assert any("'c9' 분기가 조건 목록에 없어요" in m for m in msgs)
    g["edges"][2].pop("sourceHandle")
    msgs = messages(validate_graph(g, env()))
    assert any("어떤 분기인지" in m for m in msgs)


def test_parallel_branch_rejected() -> None:
    g = base_graph()
    g["edges"].append({"id": "e9", "source": "n1", "target": "n5"})
    msgs = messages(validate_graph(g, env()))
    assert any("병렬 분기" in m for m in msgs)


def test_unknown_type_and_disallowed_type() -> None:
    g = base_graph()
    g["nodes"].append({"id": "n7", "type": "teleport", "data": {}})
    g["edges"].append({"id": "e9", "source": "n5", "target": "n7"})
    msgs = messages(validate_graph(g, env()))
    assert any("'teleport' 노드는" in m for m in msgs)
    msgs = messages(
        validate_graph(base_graph(), env(allowed_types={"input", "output", "condition"}))
    )
    assert any("'llm' 노드는" in m for m in msgs)


def test_unreachable_node() -> None:
    g = base_graph()
    g["nodes"].append({"id": "n8", "type": "output", "data": {"template": "x"}})
    msgs = messages(validate_graph(g, env()))
    assert any("이어지지 않은 노드" in m for m in msgs)


def test_connector_credential_checks() -> None:
    g = base_graph()
    g["nodes"].append(
        {
            "id": "n6",
            "type": "connector",
            "data": {
                "connector": "slack",
                "action": "post_message",
                "credential_id": "cred-x",
                "params": {},
            },
        }
    )
    g["edges"][3] = {"id": "e4", "source": "n3", "sourceHandle": "c_else", "target": "n6"}
    g["edges"].append({"id": "e5", "source": "n6", "target": "n5"})
    msgs = messages(validate_graph(g, env(credentials={}, connectors=set())))
    assert any("설치되어 있지 않아요" in m for m in msgs)
    assert any("선택한 연결 정보가 없어요" in m for m in msgs)
    ok = validate_graph(g, env(credentials={"cred-x": "slack"}, connectors={"slack"}))
    assert ok.valid, messages(ok)
    wrong = validate_graph(g, env(credentials={"cred-x": "email"}, connectors={"slack"}))
    assert any("다른 서비스의 연결 정보" in m for m in messages(wrong))


def test_malformed_graph() -> None:
    result = validate_graph({"nodes": [{"id": "1bad", "type": "input"}]}, env())
    assert not result.valid
    assert "흐름 형식" in result.errors[0].message
