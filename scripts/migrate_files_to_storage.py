"""파일·문서 본문을 DB에서 디스크/S3로 옮기는 도구(되돌리기·고아 파일 찾기 포함).

사용(컨테이너 안에서):
  docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3 --dry-run
  docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3
  docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3 --clear-db   # 확인 뒤 DB 본문 비우기
  docker compose exec api python /app/scripts/migrate_files_to_storage.py --restore-to-db          # 되돌리기
  docker compose exec api python /app/scripts/migrate_files_to_storage.py --orphans s3             # 고아 파일 목록(지우지 않음)

안전: 옮길 때마다 저장소에서 다시 읽어 크기·sha256을 맞춰 보고, --clear-db를 줄 때만 DB 본문을 비운다.
중간에 멈춰도 다시 돌리면 이어서 한다. 저장소 쪽 파일을 지우는 일은 하지 않는다.
"""

import argparse
import json
import sys
from pathlib import Path

# 컨테이너(/app/apps, /app/packages)와 저장소 루트 양쪽에서 돌릴 수 있게 경로를 잡는다
ROOT = Path(__file__).resolve().parent.parent
for sub in ("apps", "packages"):
    p = ROOT / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--target", choices=("disk", "s3"), help="옮길 저장소(기본: GENIO_STORAGE)")
    ap.add_argument("--models", default="files,documents", help="files, documents (쉼표로 구분)")
    ap.add_argument("--batch", type=int, default=200, help="한 번에 커밋할 개수")
    ap.add_argument("--limit", type=int, default=None, help="이번에 옮길 최대 개수")
    ap.add_argument("--dry-run", action="store_true", help="아무것도 바꾸지 않고 옮길 양만 센다")
    ap.add_argument(
        "--clear-db", action="store_true", help="검증 뒤 DB 본문 비우기(되돌리기는 --restore-to-db)"
    )
    ap.add_argument("--restore-to-db", action="store_true", help="저장소의 본문을 DB로 되돌린다")
    ap.add_argument(
        "--init-bucket", action="store_true", help="S3 버킷이 없으면 만든다(처음 한 번)"
    )
    ap.add_argument(
        "--orphans", choices=("disk", "s3"), help="행이 가리키지 않는 저장소 키 목록(삭제 안 함)"
    )
    args = ap.parse_args()

    from api.db import SessionLocal
    from api.services import storage, storage_migrate

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    bad = [m for m in models if m not in storage_migrate.MODELS]
    if bad:
        print(
            f"알 수 없는 대상: {', '.join(bad)} (files, documents 중에서 고르세요)", file=sys.stderr
        )
        return 2

    if args.init_bucket:
        from api.config import get_settings

        created = storage.ensure_bucket(
            storage.make_s3_client(get_settings()), get_settings().genio_s3_bucket
        )
        print(json.dumps({"bucket": get_settings().genio_s3_bucket, "created": created}))
        if not (args.target or args.restore_to_db or args.orphans):
            return 0

    with SessionLocal() as db:
        if args.orphans:
            orphans = storage_migrate.report_orphans(db, args.orphans)
            print(json.dumps({"orphans": len(orphans), "keys": orphans[:200]}, ensure_ascii=False))
            return 0
        if args.restore_to_db:
            rep = storage_migrate.restore_to_db(db, models=models, batch=args.batch)
        else:
            target = args.target or storage.configured_name()
            if target == storage.DB:
                print(
                    "옮길 저장소를 정해 주세요. --target disk|s3 를 주거나 GENIO_STORAGE를 설정하세요.",
                    file=sys.stderr,
                )
                return 2
            rep = storage_migrate.migrate_to_storage(
                db,
                target,
                models=models,
                batch=args.batch,
                dry_run=args.dry_run,
                clear_db=args.clear_db,
                limit=args.limit,
            )
    out = rep.as_dict()
    out["dry_run"] = bool(args.dry_run)
    print(json.dumps(out, ensure_ascii=False))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
