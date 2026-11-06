"""코드 단계 샌드박스 탈출 방어(2026-11 보안 점검): 허용 모듈 안에 숨은 sys·os로 빠져나가지 못한다.
정상 코드(허용 모듈의 함수 쓰기)는 그대로 동작해야 한다."""

import pytest

from api.engine.code_runner import RestrictedPythonRunner
from nodes import NodeError

ESCAPES = {
    "statistics.sys": 'import statistics\no = statistics.sys.modules["os"]\nresult = {"x": o.name}',
    "json.codecs": "import json\nresult = {'x': str(json.codecs)}",
    "re.enum": "import re\nresult = {'x': str(re.enum)}",
    "random._os": "import random\nresult = {'x': str(random._os)}",
    "datetime.sys": "import datetime\nresult = {'x': str(datetime.sys)}",
    "from import sys": "from statistics import sys\nresult = {'x': 1}",
    "os import": "import os\nresult = {'x': os.name}",
    "subprocess import": "import subprocess\nresult = {}",
    "submodule": "import datetime.sys\nresult = {}",
    "string.Formatter": (
        "import string\nresult = {'x': string.Formatter().vformat('{0.__class__}', (1,), {})}"
    ),
    "dunder class": "result = {'x': str(().__class__.__mro__)}",
    "format traversal": "result = {'x': '{0.__class__}'.format(1)}",
    "builtins getattr": "result = {'x': str(getattr(1, '__class__'))}",
    "open": "result = {'x': open('/etc/passwd').read()}",
    "eval": "result = {'x': eval('1+1')}",
    "__import__": "m = __import__('os')\nresult = {'x': m.name}",
    "itertools function globals": "import itertools\nresult = {'x': str(itertools.chain.__reduce__)}",
}


@pytest.mark.parametrize("name", list(ESCAPES))
def test_escape_attempts_are_blocked(name: str) -> None:
    runner = RestrictedPythonRunner(timeout=10)
    with pytest.raises(NodeError):
        runner.run(ESCAPES[name], {})


def test_normal_code_still_works() -> None:
    code = (
        "import json, math, re, statistics, random, string, itertools\n"
        "from datetime import datetime, timedelta\n"
        "d = datetime(2026, 12, 1) + timedelta(days=3)\n"
        "random.seed(1)\n"
        "result = {\n"
        "  'avg': statistics.mean([1, 2, 3]),\n"
        "  'sqrt': math.sqrt(16),\n"
        "  'js': json.loads(json.dumps({'a': 1}))['a'],\n"
        "  'm': re.sub(r'\\d+', '#', 'a1b22'),\n"
        "  'date': d.date().isoformat(),\n"
        "  'digits': string.digits,\n"
        "  'pairs': len(list(itertools.combinations([1, 2, 3], 2))),\n"
        "  'rnd': random.randint(1, 1),\n"
        "}\n"
    )
    out = RestrictedPythonRunner(timeout=10).run(code, {})
    assert out == {
        "avg": 2,
        "sqrt": 4.0,
        "js": 1,
        "m": "a#b#",
        "date": "2026-12-04",
        "digits": "0123456789",
        "pairs": 3,
        "rnd": 1,
    }
