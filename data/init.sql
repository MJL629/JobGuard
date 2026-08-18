-- ============================================
-- JobGuard 数据库初始化脚本
-- ============================================

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL UNIQUE COMMENT '用户名',
    email           VARCHAR(100) COMMENT '邮箱',
    phone           VARCHAR(20)  COMMENT '手机号',
    password_hash   VARCHAR(255) NOT NULL COMMENT '密码哈希',
    avatar_url      VARCHAR(500) COMMENT '头像URL',
    is_active       TINYINT(1)   DEFAULT 1 COMMENT '是否激活',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- 用户画像表
CREATE TABLE IF NOT EXISTS user_profiles (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id             BIGINT       NOT NULL UNIQUE COMMENT '用户ID',
    full_name           VARCHAR(50)  COMMENT '真实姓名',
    gender              VARCHAR(10)  COMMENT '性别',
    birth_year          INT          COMMENT '出生年份',
    degree              VARCHAR(20)  COMMENT '最高学历',
    major               VARCHAR(100) COMMENT '专业',
    school              VARCHAR(100) COMMENT '毕业院校',
    graduation_year     INT          COMMENT '毕业年份',
    current_city        VARCHAR(50)  COMMENT '当前城市',
    expected_salary_min INT          COMMENT '期望最低月薪',
    expected_salary_max INT          COMMENT '期望最高月薪',
    years_of_experience INT          DEFAULT 0 COMMENT '工作年限',
    resume_raw_text     MEDIUMTEXT   COMMENT '原始简历文本',
    resume_file_path    VARCHAR(500) COMMENT '简历文件路径',
    profile_completeness INT         DEFAULT 0 COMMENT '画像完整度',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户画像表';

-- 用户原始简历表（允许一名用户保存多份）
CREATE TABLE IF NOT EXISTS user_resumes (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id          BIGINT       NOT NULL,
    original_name    VARCHAR(255) NOT NULL,
    stored_path      VARCHAR(500) NOT NULL,
    sha256           VARCHAR(64)  NOT NULL,
    media_type       VARCHAR(120) NOT NULL,
    parser           VARCHAR(100),
    ocr_used         BOOLEAN      NOT NULL DEFAULT FALSE,
    extracted_text   MEDIUMTEXT,
    extracted_chars  INT          NOT NULL DEFAULT 0,
    structured_data  JSON,
    parse_status     VARCHAR(30)  NOT NULL DEFAULT 'pending',
    parse_error      TEXT,
    is_primary       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_resumes_user_sha256 (user_id, sha256),
    INDEX ix_user_resumes_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户多简历原始文件与解析记录';

-- 通用真实经历表（项目、实习、比赛、科研、工作等）
CREATE TABLE IF NOT EXISTS user_experiences (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id             BIGINT       NOT NULL,
    source_resume_id    BIGINT,
    experience_type     VARCHAR(30)  NOT NULL DEFAULT 'project',
    title               VARCHAR(200) NOT NULL,
    organization        VARCHAR(200),
    role                VARCHAR(100),
    description         TEXT,
    actions             TEXT,
    achievements        TEXT,
    tech_stack          JSON,
    start_date          VARCHAR(20),
    end_date            VARCHAR(20),
    evidence_text       TEXT,
    verification_status VARCHAR(30) DEFAULT 'user_confirmed',
    sort_order          INT DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (source_resume_id) REFERENCES user_resumes(id) ON DELETE SET NULL,
    INDEX ix_user_experiences_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户可核验真实经历';

-- 用户项目经历表
CREATE TABLE IF NOT EXISTS user_projects (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    project_name    VARCHAR(200) NOT NULL COMMENT '项目名称',
    role            VARCHAR(100) COMMENT '担任角色',
    description     TEXT         COMMENT '项目描述',
    tech_stack      JSON         COMMENT '技术栈',
    start_date      VARCHAR(20)  COMMENT '开始时间',
    end_date        VARCHAR(20)  COMMENT '结束时间',
    highlights      TEXT         COMMENT '项目亮点',
    project_url     VARCHAR(500) COMMENT '项目链接',
    sort_order      INT          DEFAULT 0 COMMENT '排序权重',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户项目经历表';

-- 用户技能表
CREATE TABLE IF NOT EXISTS user_skills (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    skill_name      VARCHAR(100) NOT NULL COMMENT '技能名称',
    proficiency     VARCHAR(20)  COMMENT '熟练程度',
    category        VARCHAR(50)  COMMENT '技能分类',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_skill (user_id, skill_name),
    UNIQUE KEY uk_user_skill (user_id, skill_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户技能表';

-- 教育经历表
CREATE TABLE IF NOT EXISTS education (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    school          VARCHAR(100) NOT NULL COMMENT '学校名称',
    major           VARCHAR(100) NOT NULL COMMENT '专业',
    degree          VARCHAR(20)  NOT NULL COMMENT '学历',
    start_year      INT          COMMENT '入学年份',
    end_year        INT          COMMENT '毕业年份',
    gpa             VARCHAR(10)  COMMENT 'GPA',
    honors          TEXT         COMMENT '荣誉奖项',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='教育经历表';

-- 用户偏好表
CREATE TABLE IF NOT EXISTS user_preferences (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id                 BIGINT       NOT NULL UNIQUE COMMENT '用户ID',
    preferred_job_types     JSON         COMMENT '偏好岗位类型',
    preferred_sub_categories JSON        COMMENT '偏好细分方向',
    preferred_locations     JSON         COMMENT '偏好工作城市',
    preferred_industries    JSON         COMMENT '偏好行业',
    overtime_tolerance      VARCHAR(20)  COMMENT '加班接受度',
    weekend_preference      VARCHAR(20)  COMMENT '周末偏好',
    holiday_preference      VARCHAR(20)  COMMENT '法定假日偏好',
    labor_intensity         VARCHAR(20)  COMMENT '劳动强度偏好',
    remote_work             VARCHAR(20)  COMMENT '远程工作偏好',
    company_scale_pref      VARCHAR(20)  COMMENT '公司规模偏好',
    created_at              DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户偏好表';

-- 企业信息表
CREATE TABLE IF NOT EXISTS companies (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(200) NOT NULL COMMENT '企业名称',
    industry        VARCHAR(100) COMMENT '所属行业',
    scale           VARCHAR(50)  COMMENT '企业规模',
    address         VARCHAR(300) COMMENT '企业地址',
    description     TEXT         COMMENT '企业简介',
    risk_score      DECIMAL(3,1) DEFAULT 0 COMMENT '综合风险评分',
    risk_level      VARCHAR(20)  COMMENT '风险等级',
    social_insurance_count INT   COMMENT '社保参保人数',
    labor_dispute_count    INT   DEFAULT 0 COMMENT '劳动争议数量',
    reputation_score       DECIMAL(3,1) COMMENT '网络口碑评分',
    last_checked    DATETIME     COMMENT '最后检查时间',
    data_source     VARCHAR(50)  COMMENT '数据来源',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_name (name),
    INDEX idx_risk_level (risk_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业信息表';

-- 企业背调证据表：所有外部事实必须绑定可核验来源
CREATE TABLE IF NOT EXISTS company_evidence (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_id          BIGINT       NOT NULL COMMENT '企业ID',
    company_name        VARCHAR(200) NOT NULL COMMENT '查询时使用的企业名称',
    evidence_type       VARCHAR(50)  NOT NULL COMMENT '证据类型',
    source_kind         VARCHAR(30)  NOT NULL COMMENT 'official/job_board/media/user_provided',
    source_name         VARCHAR(200) NOT NULL COMMENT '来源名称',
    source_url          VARCHAR(1000) NOT NULL COMMENT '可核验来源链接',
    title               VARCHAR(300) NOT NULL COMMENT '证据标题',
    content_excerpt     TEXT         COMMENT '支持结论的最小必要原文摘录',
    structured_data     JSON         COMMENT '来源中直接提取的结构化字段',
    source_hash         VARCHAR(64)  NOT NULL COMMENT '幂等来源指纹',
    is_verified         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否为白名单官方来源',
    verification_level  VARCHAR(30)  NOT NULL DEFAULT 'reported',
    published_at        DATETIME     COMMENT '来源发布时间',
    observed_at         DATETIME     NOT NULL COMMENT '采集时间',
    created_by_user_id  BIGINT       COMMENT '录入用户ID',
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE KEY uq_company_evidence_source_hash (source_hash),
    INDEX idx_company_evidence_company_type (company_id, evidence_type),
    INDEX idx_company_evidence_observed (observed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业背调证据表';

-- 岗位信息表
CREATE TABLE IF NOT EXISTS jobs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_name    VARCHAR(200) NOT NULL COMMENT '公司名称',
    company_id      BIGINT       COMMENT '关联企业ID',
    job_title       VARCHAR(200) NOT NULL COMMENT '岗位名称',
    job_category    VARCHAR(50)  NOT NULL COMMENT '岗位大类',
    sub_category    VARCHAR(100) COMMENT '岗位细分',
    salary_min      INT          COMMENT '最低月薪',
    salary_max      INT          COMMENT '最高月薪',
    location        VARCHAR(100) COMMENT '工作地点',
    jd_text         MEDIUMTEXT   COMMENT '岗位描述原文',
    requirements    JSON         COMMENT '技术要求',
    benefits        JSON         COMMENT '福利待遇',
    source_url      VARCHAR(1000) COMMENT '来源链接',
    source_type     VARCHAR(50)  COMMENT '来源平台',
    source_external_id VARCHAR(255) COMMENT '来源平台岗位ID',
    source_published_at DATETIME COMMENT '来源平台发布时间',
    posted_at       DATETIME     COMMENT '发布日期',
    expires_at      DATETIME     COMMENT '岗位有效期截止时间',
    last_seen_at    DATETIME     COMMENT '最后一次在来源中观测到的时间',
    is_active       TINYINT(1)   DEFAULT 1 COMMENT '是否有效',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    INDEX idx_category (job_category, sub_category),
    INDEX idx_company (company_name),
    INDEX idx_location (location),
    INDEX idx_posted (posted_at),
    INDEX idx_jobs_expires_at (expires_at),
    INDEX idx_jobs_last_seen_at (last_seen_at),
    UNIQUE KEY uq_jobs_source_external_id (source_type, source_external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位信息表';

-- 岗位分析记录表
CREATE TABLE IF NOT EXISTS job_analyses (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id          BIGINT       COMMENT '岗位ID',
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    company_name    VARCHAR(200) NOT NULL COMMENT '公司名称',
    job_title       VARCHAR(200) COMMENT '岗位名称',
    risk_level      VARCHAR(20)  COMMENT '风险等级',
    recommendation_index INT     COMMENT '推荐指数 1-5',
    match_score     DECIMAL(5,2) COMMENT '匹配度百分比',
    analysis_json   JSON         COMMENT '完整分析结果',
    source_type     VARCHAR(50)  COMMENT '分析触发方式',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_job (user_id, job_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位分析记录表';

-- 生成简历记录表
CREATE TABLE IF NOT EXISTS generated_resumes (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id             BIGINT       NOT NULL COMMENT '用户ID',
    job_id              BIGINT       COMMENT '关联岗位ID',
    job_title           VARCHAR(200) COMMENT '目标岗位名称',
    company_name        VARCHAR(200) COMMENT '目标公司名称',
    resume_markdown     MEDIUMTEXT   COMMENT '简历 Markdown',
    greeting_text       TEXT         COMMENT '招呼语',
    selected_projects   JSON         COMMENT '选中的项目ID及排序',
    self_evaluation     TEXT         COMMENT '自我评价段落',
    pdf_path            VARCHAR(500) COMMENT 'PDF文件路径',
    docx_path           VARCHAR(500) COMMENT 'DOCX文件路径',
    template_id         VARCHAR(50)  DEFAULT 'template-01' COMMENT '生成模板ID',
    version             INT          DEFAULT 1 COMMENT '版本号',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
    INDEX idx_user_job (user_id, job_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='生成简历记录表';

-- 对话会话表
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    session_type    VARCHAR(50)  NOT NULL COMMENT '会话类型',
    status          VARCHAR(20)  DEFAULT 'active' COMMENT '状态',
    context_json    JSON         COMMENT '会话上下文',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_session (user_id, session_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话表';

-- 对话消息表
CREATE TABLE IF NOT EXISTS chat_messages (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id      BIGINT       NOT NULL COMMENT '会话ID',
    role            VARCHAR(20)  NOT NULL COMMENT '角色',
    content         MEDIUMTEXT   NOT NULL COMMENT '消息内容',
    message_type    VARCHAR(50)  DEFAULT 'text' COMMENT '消息类型',
    metadata_json   JSON         COMMENT '附加元数据',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE,
    INDEX idx_session (session_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息表';
