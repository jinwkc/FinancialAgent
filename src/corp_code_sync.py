"""OpenDART corpCode.xml을 비동기적으로 관계형 데이터베이스에 동기화한다.

기본 연결 대상은 현재 개발 환경의 MySQL이다. ``CORP_CODE_DATABASE_URL`` 환경변수로
다른 SQLAlchemy 연결 문자열을 지정할 수 있다. MySQL 동기화는 named lock으로
동시에 하나만 실행하고, 일반 조회는 SQLAlchemy 비동기 커넥션 풀을 사용한다.

인증키는 ``DART_API_KEY`` 또는 ``OPENDART_API_KEY`` 환경변수에서만 읽으며,
소스 코드나 데이터베이스에 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    desc,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# CorpCode 전용 MySQL 연결 문자열을 읽을 환경변수 이름이다.
# 일반 애플리케이션의 SQLite ``DATABASE_URL``과 충돌하지 않도록 별도로 둔다.
CORP_CODE_DATABASE_URL_ENV = "CORP_CODE_DATABASE_URL"
SYNC_LOCK_NAME = "opendart_corp_code_sync"
SYNC_LOCK_TIMEOUT_SECONDS = 30


class Base(DeclarativeBase):
    """CorpCode 동기화 테이블의 SQLAlchemy 기본 클래스."""


class CorpCode(Base):
    """현재 사용 가능한 OpenDART 기업 고유번호 마스터 데이터."""

    __tablename__ = "dart_corp_codes"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    corp_eng_name: Mapped[str | None] = mapped_column(String(200))
    stock_code: Mapped[str | None] = mapped_column(String(6))
    modify_date: Mapped[str | None] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CorpCodeSyncRun(Base):
    """다운로드한 corpCode.xml 스냅샷별 동기화 이력."""

    __tablename__ = "dart_corp_code_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retired_count: Mapped[int] = mapped_column(Integer, nullable=False)


@dataclass(frozen=True)
class SyncResult:
    """CorpCode 동기화 결과."""

    source_sha256: str
    source_record_count: int
    inserted_count: int
    changed_count: int
    retired_count: int
    skipped: bool


def get_api_key() -> str:
    """실행 환경에서 OpenDART 인증키를 읽는다."""

    api_key = os.getenv("DART_API_KEY") or os.getenv("OPENDART_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DART_API_KEY 또는 OPENDART_API_KEY 환경변수가 설정되어 있지 않습니다."
        )
    return api_key


def download_corp_code_zip(api_key: str, timeout: float = 30.0) -> bytes:
    """동기 호환 래퍼도 callImportant.py를 통해 ZIP을 내려받는다."""
    return asyncio.run(async_download_corp_code_zip(api_key, timeout))


async def async_download_corp_code_zip(api_key: str, timeout: float = 30.0) -> bytes:
    """CorpCode ZIP 호출을 공통 OpenDART API 클라이언트에 위임한다."""
    from app.callImportant import OpenDartImportantClient

    async with OpenDartImportantClient(api_key=api_key, timeout=timeout) as client:
        return await client.get_corp_code_zip()


def parse_corp_code_zip(zip_bytes: bytes) -> list[dict[str, str]]:
    """ZIP 내부 XML에서 DB에 저장할 기업 필드만 정규화한다."""

    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        xml_files = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_files:
            raise ValueError("ZIP 파일 내부에 XML 파일이 없습니다.")
        root = ET.fromstring(archive.read(xml_files[0]))

    records: list[dict[str, str]] = []
    for item in root.findall(".//list"):
        def value(tag: str) -> str:
            return (item.findtext(tag) or "").strip()

        corp_code = value("corp_code")
        corp_name = value("corp_name")
        if len(corp_code) != 8 or not corp_name:
            continue
        records.append(
            {
                "corp_code": corp_code,
                "corp_name": corp_name,
                "corp_eng_name": value("corp_eng_name"),
                "stock_code": value("stock_code"),
                "modify_date": value("modify_date"),
            }
        )
    return records


def _async_database_url(database_url: str | None) -> str:
    """동기 MySQL URL을 asyncmy 드라이버 URL로 변환한다."""

    # 로컬 실행 시 .env를 읽고, 인자로 받은 URL이 없으면 전용 환경변수를 사용한다.
    load_dotenv()
    url = database_url or os.getenv(CORP_CODE_DATABASE_URL_ENV)
    if not url:
        raise ValueError(
            f"{CORP_CODE_DATABASE_URL_ENV} 환경변수 또는 database_url 인자가 필요합니다."
        )
    if url.startswith("mysql+pymysql://"):
        return url.replace("mysql+pymysql://", "mysql+asyncmy://", 1)
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+asyncmy://", 1)
    if url.startswith("mysql+asyncmy://"):
        return url
    raise ValueError(
        "비동기 CorpCode 동기화는 MySQL URL만 지원합니다. "
        "mysql+pymysql:// 또는 mysql+asyncmy:// URL을 사용하세요."
    )


def create_corp_code_async_engine(database_url: str | None = None):
    """동시 Agent 요청을 처리할 비동기 MySQL 엔진과 커넥션 풀을 생성한다."""

    return create_async_engine(
        _async_database_url(database_url),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
    )


def create_corp_code_session_factory(database_url: str | None = None):
    """Agent 서비스가 재사용할 비동기 엔진과 세션 팩토리를 함께 만든다.

    애플리케이션 시작 시 한 번 생성하고, 종료 시 반환된 엔진의 ``dispose``를
    호출한다. 요청마다 엔진을 새로 만들지 않아 커넥션 풀을 공유할 수 있다.
    """

    engine = create_corp_code_async_engine(database_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory


async def find_corp_codes_by_name(
    company_name: str,
    database_url: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """기업명으로 활성 CorpCode 후보를 비동기 검색한다.

    정확히 일치하는 기업명을 먼저 찾고, 결과가 없으면 부분 일치로 검색한다.
    Agent가 후보가 여러 개인 경우 사용자에게 재선택을 요청할 수 있도록
    ``corp_code``와 기업 식별 정보를 딕셔너리 목록으로 반환한다.

    Args:
        company_name: 검색할 기업명(예: ``"삼성전자"``).
        database_url: 선택적 MySQL SQLAlchemy URL.
        limit: 반환할 최대 후보 수.

    Returns:
        ``corp_code``, 기업명, 영문명, 종목코드, 수정일을 담은 딕셔너리 목록.
    """

    normalized_name = company_name.strip()
    if not normalized_name:
        raise ValueError("company_name은 비어 있을 수 없습니다.")
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    engine, session_factory = create_corp_code_session_factory(database_url)
    try:
        async with session_factory() as session:
            base_query = select(CorpCode).where(CorpCode.is_active.is_(True))
            exact_query = (
                base_query.where(CorpCode.corp_name == normalized_name)
                .order_by(CorpCode.corp_name, CorpCode.corp_code)
                .limit(limit)
            )
            rows = (await session.scalars(exact_query)).all()
            if not rows:
                partial_query = (
                    base_query.where(CorpCode.corp_name.like(f"%{normalized_name}%"))
                    .order_by(CorpCode.corp_name, CorpCode.corp_code)
                    .limit(limit)
                )
                rows = (await session.scalars(partial_query)).all()
            return [
                {
                    "corp_code": row.corp_code,
                    "corp_name": row.corp_name,
                    "corp_eng_name": row.corp_eng_name,
                    "stock_code": row.stock_code,
                    "modify_date": row.modify_date,
                }
                for row in rows
            ]
    finally:
        await engine.dispose()


async def _acquire_sync_lock(connection: AsyncConnection) -> None:
    """동기화 작업을 한 번에 하나만 실행하도록 MySQL named lock을 획득한다."""

    locked = await connection.scalar(
        text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
        {
            "lock_name": SYNC_LOCK_NAME,
            "timeout_seconds": SYNC_LOCK_TIMEOUT_SECONDS,
        },
    )
    await connection.commit()
    if locked != 1:
        raise TimeoutError("다른 CorpCode 동기화가 실행 중이어서 잠금을 획득하지 못했습니다.")


async def _release_sync_lock(connection: AsyncConnection) -> None:
    """획득한 MySQL named lock을 같은 연결에서 해제한다."""

    await connection.execute(
        text("SELECT RELEASE_LOCK(:lock_name)"),
        {"lock_name": SYNC_LOCK_NAME},
    )
    await connection.commit()


async def _sync_corp_codes_with_session(
    session: AsyncSession,
    api_key: str,
    archive_path: str | Path | None,
    timeout: float,
) -> SyncResult:
    """잠금을 보유한 세션에서 다운로드·비교·일괄 반영을 수행한다."""

    zip_bytes = await async_download_corp_code_zip(api_key, timeout=timeout)
    source_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    records = parse_corp_code_zip(zip_bytes)

    if archive_path is not None:
        archive = Path(archive_path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(zip_bytes)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing_count = await session.scalar(select(func.count()).select_from(CorpCode)) or 0
    previous = await session.scalar(
        select(CorpCodeSyncRun)
        .order_by(desc(CorpCodeSyncRun.fetched_at))
        .limit(1)
    )
    if previous and previous.source_sha256 == source_sha256 and existing_count:
        return SyncResult(source_sha256, len(records), 0, 0, 0, True)

    current = {
        row.corp_code: row
        for row in (await session.scalars(select(CorpCode))).all()
    }
    incoming_codes = {record["corp_code"] for record in records}
    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    # 실제 기업 정보만 비교한다. 조회 시각 필드는 비교에서 제외해
    # 원본 정보가 변경되지 않았을 때 불필요한 UPDATE가 발생하지 않게 한다.
    business_fields = (
        "corp_name",
        "corp_eng_name",
        "stock_code",
        "modify_date",
        "is_active",
    )

    for record in records:
        code = record["corp_code"]
        row = current.get(code)
        values = {
            **record,
            "is_active": True,
            "last_seen_at": now,
            "updated_at": now,
        }
        if row is None:
            inserts.append(values)
        elif any(
            getattr(row, field) != values[field]
            for field in business_fields
        ):
            updates.append({"corp_code": code, **values})

    retired = [
        {"corp_code": code, "is_active": False, "updated_at": now}
        for code, row in current.items()
        if code not in incoming_codes and row.is_active
    ]

    if inserts:
        await session.execute(insert(CorpCode), inserts)
    if updates:
        await session.execute(update(CorpCode), updates)
    if retired:
        await session.execute(update(CorpCode), retired)

    session.add(
        CorpCodeSyncRun(
            fetched_at=now,
            source_sha256=source_sha256,
            source_record_count=len(records),
            inserted_count=len(inserts),
            changed_count=len(updates),
            retired_count=len(retired),
        )
    )
    await session.commit()
    return SyncResult(
        source_sha256,
        len(records),
        len(inserts),
        len(updates),
        len(retired),
        False,
    )


async def async_sync_corp_codes(
    database_url: str | None = None,
    api_key: str | None = None,
    archive_path: str | Path | None = None,
    timeout: float = 30.0,
) -> SyncResult:
    """비동기 방식으로 CorpCode를 동기화한다.

    MySQL named lock이 연결된 상태에서 유지되므로 여러 Agent worker가 동시에
    호출해도 한 작업만 쓰기 작업을 수행한다. 일반 조회 세션은 별도 풀에서
    병렬로 처리할 수 있다.
    """

    engine = create_corp_code_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with engine.connect() as connection:
            await _acquire_sync_lock(connection)
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    return await _sync_corp_codes_with_session(
                        session,
                        api_key or get_api_key(),
                        archive_path,
                        timeout,
                    )
            finally:
                await _release_sync_lock(connection)
    finally:
        await engine.dispose()


def sync_corp_codes(
    database_url: str | None = None,
    api_key: str | None = None,
    archive_path: str | Path | None = None,
    timeout: float = 30.0,
) -> SyncResult:
    """기존 동기 호출자를 위한 래퍼이다. 비동기 서버에서는 async 함수를 사용한다."""

    return asyncio.run(
        async_sync_corp_codes(database_url, api_key, archive_path, timeout)
    )


async def async_get_company_json(
    corp_code: str,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """company.json 원본 응답을 비동기 Python 딕셔너리로 반환한다."""

    if len(corp_code) != 8 or not corp_code.isdigit():
        raise ValueError("corp_code는 숫자 8자리여야 합니다.")
    from app.callImportant import OpenDartImportantClient

    async with OpenDartImportantClient(api_key=api_key or get_api_key(), timeout=timeout) as client:
        return await client.call_json_api("company.json", {"corp_code": corp_code})


def get_company_json(
    corp_code: str,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """기존 동기 호출자를 위한 company.json 조회 래퍼이다."""

    return asyncio.run(async_get_company_json(corp_code, api_key, timeout))


async def _async_main() -> None:
    """CLI에서 동기화 결과와 선택적 company.json을 출력한다."""

    parser = argparse.ArgumentParser(
        description="OpenDART corpCode.xml을 비동기 방식으로 MySQL에 동기화합니다."
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--archive-path", default=None)
    parser.add_argument("--company-corp-code", default=None)
    args = parser.parse_args()

    result = await async_sync_corp_codes(
        database_url=args.database_url,
        archive_path=args.archive_path,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))

    if args.company_corp_code:
        company = await async_get_company_json(args.company_corp_code)
        print(json.dumps(company, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_async_main())
