"""데모 데이터 시드(설계서 §11 5단계). 사용자가 한 명도 없을 때만 만든다.

계정(비밀번호 공통: genio1234!):
  owner@example.com / admin@example.com / builder@example.com / operator@example.com / member@example.com
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.security import hash_password
from api.market import service as market
from api.models import MarketItem, Membership, Organization, User, Workspace

log = logging.getLogger("genio.seed")
DEMO_PASSWORD = "genio1234!"  # noqa: S105 - 데모 계정용 공개 비밀번호
DEMO_USERS = [
    ("owner@example.com", "김오너", "owner"),
    ("admin@example.com", "이관리", "admin"),
    ("builder@example.com", "박빌더", "builder"),
    ("operator@example.com", "최운영", "operator"),
    ("member@example.com", "정멤버", "member"),
]


def seed_demo(db: Session) -> bool:
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        return False
    org = Organization(name="데모 회사", slug="demo")
    db.add(org)
    db.flush()
    ws = Workspace(org_id=org.id, name="데모 회사", slug="demo", settings={"locale": "ko"})
    db.add(ws)
    db.flush()
    pw = hash_password(DEMO_PASSWORD)
    owner_id = ""
    for email, name, role in DEMO_USERS:
        u = User(email=email, name=name, password_hash=pw)
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, workspace_id=ws.id, role=role))
        if role == "owner":
            owner_id = u.id
    db.commit()
    # 템플릿·프롬프트 팩은 미리 설치해 둔다. 커넥터는 데모 시나리오에서 마켓으로 설치한다.
    for item in db.scalars(
        select(MarketItem).where(MarketItem.type.in_(["template", "prompt_pack"]))
    ):
        market.install(db, ws.id, item.key, owner_id)
    log.info("데모 데이터를 만들었어요(워크스페이스: %s)", ws.name)
    return True
