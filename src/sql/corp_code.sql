-- OpenDART CorpCode 마스터용 MySQL 스키마
-- 현재 MySQL 컨테이너의 dart 데이터베이스 대상

CREATE DATABASE IF NOT EXISTS dart
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE dart;

-- 고유번호·기업명·영문명·종목코드·동기화 상태
CREATE TABLE IF NOT EXISTS dart_corp_codes (
    corp_code CHAR(8) NOT NULL,
    corp_name VARCHAR(200) NOT NULL,
    corp_eng_name VARCHAR(200) NULL,
    stock_code CHAR(6) NULL,
    modify_date CHAR(8) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (corp_code),
    INDEX idx_dart_corp_codes_name (corp_name),
    INDEX idx_dart_corp_codes_stock_code (stock_code),
    INDEX idx_dart_corp_codes_active (is_active)
) ENGINE=InnoDB;

-- 원본 ZIP 해시와 동기화 이력
CREATE TABLE IF NOT EXISTS dart_corp_code_sync_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    fetched_at DATETIME NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    source_record_count INT UNSIGNED NOT NULL,
    inserted_count INT UNSIGNED NOT NULL,
    changed_count INT UNSIGNED NOT NULL,
    retired_count INT UNSIGNED NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_dart_sync_hash (source_sha256),
    INDEX idx_dart_sync_fetched_at (fetched_at)
) ENGINE=InnoDB;
