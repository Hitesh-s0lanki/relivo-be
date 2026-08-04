CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(200) PRIMARY KEY,
    external_id VARCHAR(200),
    email VARCHAR(320),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    phone_number VARCHAR(30),
    username VARCHAR(200),
    first_name VARCHAR(200),
    last_name VARCHAR(200),
    full_name VARCHAR(400),
    image_url VARCHAR(1024),
    has_image BOOLEAN NOT NULL DEFAULT FALSE,
    work_function VARCHAR(100),
    job_title VARCHAR(200),
    company_name VARCHAR(200),
    industry VARCHAR(100),
    team_size VARCHAR(30),
    timezone VARCHAR(64),
    locale VARCHAR(20),
    onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    public_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    private_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    unsafe_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    password_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    banned BOOLEAN NOT NULL DEFAULT FALSE,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    last_sign_in_at TIMESTAMP WITH TIME ZONE,
    last_active_at TIMESTAMP WITH TIME ZONE,
    clerk_created_at TIMESTAMP WITH TIME ZONE,
    clerk_updated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_users_email
    ON users(email);

CREATE INDEX IF NOT EXISTS ix_users_username
    ON users(username);

CREATE INDEX IF NOT EXISTS ix_users_external_id
    ON users(external_id);

CREATE INDEX IF NOT EXISTS ix_users_work_function
    ON users(work_function);

CREATE INDEX IF NOT EXISTS ix_users_created_at
    ON users(created_at);
