-- learn_langChain · 基础业务表
-- 用户、对话会话、对话消息
-- MySQL 8.4 / utf8mb4

SET NAMES utf8mb4;
SET time_zone = '+08:00';

USE langchain;

-- 用户
CREATE TABLE IF NOT EXISTS app_user (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username      VARCHAR(64)     NOT NULL COMMENT '登录名',
  display_name  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '显示名',
  email         VARCHAR(128)    NULL,
  password_hash VARCHAR(255)    NOT NULL COMMENT '仅存哈希，禁止存明文',
  role          ENUM('admin','member') NOT NULL DEFAULT 'member',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '1 启用 0 停用',
  last_login_at DATETIME        NULL,
  created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_username (username),
  UNIQUE KEY uk_user_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户';

-- 对话会话：一个用户可以有多个会话
CREATE TABLE IF NOT EXISTS chat_session (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     BIGINT UNSIGNED NOT NULL,
  title       VARCHAR(255)    NOT NULL DEFAULT '新会话',
  model       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '使用的模型名，如 deepseek-v4-flash',
  status      ENUM('active','archived') NOT NULL DEFAULT 'active',
  created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_session_user_updated (user_id, updated_at),
  CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES app_user (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话';

-- 对话消息
CREATE TABLE IF NOT EXISTS chat_message (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_id  BIGINT UNSIGNED NOT NULL,
  role        ENUM('system','user','assistant','tool') NOT NULL,
  content     MEDIUMTEXT      NULL COMMENT '正文',
  reasoning   MEDIUMTEXT      NULL COMMENT '思考模型的 reasoning_content，需回传时使用',
  tool_calls  JSON            NULL COMMENT 'assistant 发起的工具调用',
  tool_call_id VARCHAR(64)    NULL COMMENT 'role=tool 时对应的调用 id',
  token_in    INT UNSIGNED    NOT NULL DEFAULT 0,
  token_out   INT UNSIGNED    NOT NULL DEFAULT 0,
  created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_message_session_created (session_id, created_at),
  CONSTRAINT fk_message_session FOREIGN KEY (session_id) REFERENCES chat_session (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息';

-- 版本号递增
INSERT INTO schema_meta (key_name, value_text) VALUES ('schema_version', '2')
ON DUPLICATE KEY UPDATE value_text = VALUES(value_text);

-- 示例用户：密码为占位哈希，不可用于登录
INSERT INTO app_user (username, display_name, email, password_hash, role) VALUES
  ('admin',  '管理员', 'admin@example.com',  '!placeholder-not-a-real-hash', 'admin'),
  ('demo',   '演示用户', 'demo@example.com', '!placeholder-not-a-real-hash', 'member')
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);
