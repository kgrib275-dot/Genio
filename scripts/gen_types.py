"""그래프 JSON Schema를 프런트로 내보낸다.

실행: PYTHONPATH=apps:packages python scripts/gen_types.py
그 다음 apps/web 에서 `npm run gen:types` 가 TypeScript 타입을 만든다.
"""

import json
from pathlib import Path

from api.schemas.graph import Graph

OUT = Path(__file__).resolve().parent.parent / "apps/web/src/lib/api/generated/graph.schema.json"


def main() -> None:
    schema = Graph.model_json_schema(by_alias=True, mode="serialization")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
