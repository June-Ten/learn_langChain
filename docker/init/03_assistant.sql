-- 内部助手业务表。已有数据卷不会重放本脚本，应用启动时也会 CREATE TABLE IF NOT EXISTS。
-- MySQL 8.4 / utf8mb4

SET NAMES utf8mb4;
SET time_zone = '+08:00';

USE langchain;

CREATE TABLE IF NOT EXISTS employees (
  id          VARCHAR(16)  NOT NULL,
  name        VARCHAR(64)  NOT NULL,
  department  VARCHAR(64)  NOT NULL,
  title       VARCHAR(64)  NOT NULL,
  email       VARCHAR(128) NOT NULL,
  role        VARCHAR(16)  NOT NULL,
  manager_id  VARCHAR(16)  NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工';

CREATE TABLE IF NOT EXISTS tickets (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  title        VARCHAR(80)     NOT NULL,
  description  TEXT            NOT NULL,
  category     VARCHAR(16)     NOT NULL,
  priority     VARCHAR(16)     NOT NULL,
  status       VARCHAR(16)     NOT NULL,
  requester_id VARCHAR(16)     NOT NULL,
  created_at   VARCHAR(40)     NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_ticket_employee FOREIGN KEY (requester_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单';

CREATE TABLE IF NOT EXISTS conversations (
  id          VARCHAR(32) NOT NULL,
  user_id     VARCHAR(16) NOT NULL,
  title       VARCHAR(40) NOT NULL,
  created_at  VARCHAR(40) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_conversation_employee FOREIGN KEY (user_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话';

CREATE TABLE IF NOT EXISTS messages (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id  VARCHAR(32)     NOT NULL,
  role             VARCHAR(16)     NOT NULL,
  content          TEXT            NOT NULL,
  created_at       VARCHAR(40)     NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id) REFERENCES conversations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话消息';

CREATE TABLE IF NOT EXISTS audit_logs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  actor_id    VARCHAR(16)     NOT NULL,
  action      VARCHAR(64)     NOT NULL,
  resource    VARCHAR(64)     NOT NULL,
  detail      VARCHAR(500)    NOT NULL,
  created_at  VARCHAR(40)     NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审计';

CREATE TABLE IF NOT EXISTS knowledge_notes (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  title       VARCHAR(80)     NOT NULL,
  body        TEXT            NOT NULL,
  author_id   VARCHAR(16)     NOT NULL,
  created_at  VARCHAR(40)     NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库笔记';
