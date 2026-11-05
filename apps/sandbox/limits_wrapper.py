"""자식 프로세스 시작 도우미: 자원 제한을 건 뒤 실제 실행기(py_child·js_child)를 같은 프로세스에서 돌린다.

사용: python -I limits_wrapper.py <cpu초> <메모리MB> <실행기 경로>
- 리눅스에서만 resource 제한(CPU·주소 공간·파일 수·파일 크기·프로세스 수)을 건다. 다른 OS는 건너뛴다.
- stdin/stdout은 그대로 실행기에 넘어간다.
"""

import runpy
import sys


def apply_limits(cpu_seconds: int, memory_mb: int) -> None:
    if sys.platform == "win32":  # 윈도: 제한 없이 실행(운영은 리눅스 컨테이너)
        return
    import resource

    mem = max(64, memory_mb) * 1024 * 1024

    def lim(kind: int, soft: int) -> None:
        try:
            _s, hard = resource.getrlimit(kind)
            soft = soft if hard in (-1, resource.RLIM_INFINITY) else min(soft, hard)
            resource.setrlimit(kind, (soft, soft if hard in (-1, resource.RLIM_INFINITY) else hard))
        except (ValueError, OSError):
            pass

    lim(resource.RLIMIT_CPU, max(1, cpu_seconds))
    lim(resource.RLIMIT_AS, mem)
    lim(resource.RLIMIT_NOFILE, 32)
    lim(resource.RLIMIT_FSIZE, 1024 * 1024)
    lim(resource.RLIMIT_CORE, 0)
    if hasattr(resource, "RLIMIT_NPROC"):
        lim(resource.RLIMIT_NPROC, 1)  # 새 프로세스·스레드를 거의 못 만들게


def main() -> None:
    cpu, mem, target = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    apply_limits(cpu, mem)
    sys.argv = [target]
    runpy.run_path(target, run_name="__main__")


if __name__ == "__main__":
    main()
