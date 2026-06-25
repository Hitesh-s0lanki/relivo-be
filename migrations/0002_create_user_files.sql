CREATE TABLE IF NOT EXISTS user_files (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(200) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(255),
    file_category VARCHAR(30) NOT NULL,
    size_bytes BIGINT NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    s3_bucket VARCHAR(255) NOT NULL,
    s3_key VARCHAR(1024) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_user_files_s3_key UNIQUE (s3_key)
);

CREATE INDEX IF NOT EXISTS ix_user_files_user_id
    ON user_files(user_id);

CREATE INDEX IF NOT EXISTS ix_user_files_file_category
    ON user_files(file_category);

CREATE INDEX IF NOT EXISTS ix_user_files_checksum_sha256
    ON user_files(checksum_sha256);

CREATE INDEX IF NOT EXISTS ix_user_files_created_at
    ON user_files(created_at);
