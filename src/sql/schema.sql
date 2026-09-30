-- Company 테이블 DDL
CREATE TABLE IF NOT EXISTS companies (
    corp_code VARCHAR(8) PRIMARY KEY,
    corp_name VARCHAR(100) NOT NULL,
    stock_code VARCHAR(6),
    modify_date VARCHAR(8),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 재무보고서 테이블 정의
CREATE TABLE IF NOT EXISTS financial_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corp_code VARCHAR(8) NOT NULL,
    bsns_year VARCHAR(4) NOT NULL,
    reprt_code VARCHAR(5) NOT NULL,
    account_nm VARCHAR(100) NOT NULL,
    thstrm_amount BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (corp_code) REFERENCES companies(corp_code) ON DELETE CASCADE
);

-- 조회 성능용 인덱스
CREATE INDEX IF NOT EXISTS idx_financial_reports_corp_year
ON financial_reports (corp_code, bsns_year);
