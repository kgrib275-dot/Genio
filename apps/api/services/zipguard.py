"""압축 폭탄 막기(운영 준비 1차 B1·F7).

XLSX·DOCX·PPTX는 zip이다. 작은 파일이 풀면 수 GB가 되도록 만든 파일(압축 폭탄)을 열면
서버 메모리가 바닥난다. 열기 전에 zip 목차만 읽어 풀린 크기·항목 수·압축률을 확인한다.
"""

import io
import zipfile

# 풀린 크기 합계, 항목 수, 항목 하나의 최대 압축률
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_RATIO = 200


class ZipBombError(ValueError):
    """사람이 읽을 두 줄 문장(무엇이 문제인지 + 어떻게 하면 되는지)."""

    def parts(self) -> tuple[str, str]:
        message, _, hint = str(self).partition("\n")
        return message, hint


def check_zip(content: bytes, *, max_bytes: int = MAX_UNCOMPRESSED_BYTES) -> None:
    """오피스 파일(zip)이 풀었을 때 너무 커지면 ZipBombError. zip이 아니면 그냥 둔다(열 때 오류)."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return
    if len(infos) > MAX_ENTRIES:
        raise ZipBombError(
            "파일 안에 들어 있는 항목이 너무 많아 열 수 없어요.\n"
            "내용을 나눠 여러 파일로 올려 주세요."
        )
    total = 0
    for info in infos:
        total += max(0, info.file_size)
        if info.compress_size > 0 and info.file_size / info.compress_size > MAX_RATIO:
            raise ZipBombError(
                "파일을 풀면 비정상적으로 커져서 열 수 없어요(압축 폭탄으로 보여요).\n"
                "원래 프로그램에서 다시 저장한 파일을 올려 주세요."
            )
        if total > max_bytes:
            raise ZipBombError(
                f"파일을 풀면 {max_bytes // (1024 * 1024)}MB를 넘어 열 수 없어요.\n"
                "내용을 나눠 여러 파일로 올려 주세요."
            )
