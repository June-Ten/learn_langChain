-- learn_langChain · 本地开发库基础结构
-- 只建基础表，后续按需补充
-- MySQL 8.4 / utf8mb4

SET NAMES utf8mb4;
SET time_zone = '+08:00';

USE langchain;

-- 通用元信息表：记录本地库结构版本，方便后续做迁移
CREATE TABLE IF NOT EXISTS schema_meta (
  key_name    VARCHAR(64)  NOT NULL,
  value_text  VARCHAR(512) NOT NULL DEFAULT '',
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (key_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='库结构元信息';

INSERT INTO schema_meta (key_name, value_text) VALUES ('schema_version', '1')
ON DUPLICATE KEY UPDATE value_text = VALUES(value_text);
