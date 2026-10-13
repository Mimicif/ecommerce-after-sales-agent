# GitHub 开源发布记录

日期：2026-10-13（Asia/Shanghai）。用户已明确授权公开同步，并确认仓库名与 MIT 许可证。

- 仓库：https://github.com/Mimicif/ecommerce-after-sales-agent
- 公开分支：main；本地发布分支：codex/open-source。
- 许可证：根目录 LICENSE（MIT，版权署名 Mimicif）。
- 版本：应用0.6.0、API api-v1-m5、schema0005_m4、checkpoint-v2-m6；业务实现和冻结评测版本不变。

## 发布范围

包含后端、前端、迁移、启动与测试脚本、两份依赖锁、模拟数据、评测集/历史报告、验收文档与已检查证据。历史失败成绩继续保留，不重写为成功。

`.gitattributes` 禁止 Git 自动转换换行，保留既有 LF/CRLF 文件的实际字节，使冻结实现和验收 SHA256 在克隆后仍可核对。

排除 .env 与其他实际环境配置、.runtime、.venv、node_modules、数据库、缓存、日志、构建目录、dist源码包、视频、.pem/.key私钥。它们留在本地，不通过 Git 分发。评测与业务数据均来自本项目模拟数据；不包含真实客户业务数据。发布检查比对本地实际供应商密钥、数据库URL/密码与管理员密码，检查常见凭据格式。匹配到的 SQLAlchemy 数据库地址已脱敏，配置安全测试使用 u:p 假值，安装脚本中的密码是变量引用；这些均非真实凭据。

## 运行与验证

按 README 克隆、安装、迁移、seed，并启动 API、Agent worker、模拟退款 worker 与前端。模型密钥自行在本地配置；没有密钥仍可验证确定性后端，聊天不能伪造成功。

本次检查文档链接、模拟数据结构、发布文件凭据、Git排除规则以及 M6 候选中实际后端/前端/脚本/数据/评测文件的SHA256。没有重新运行311项PostgreSQL回归、浏览器三剧本或live模型评测；这些历史成绩对应 docs/18_M6_ACCEPTANCE.md 和原验收文件，不称为本次新成绩。

原 `scripts/verify_m6.py` 用于本地历史交付包：依赖本地视频，并核对原候选 `.gitignore` 等文件哈希。本次为开源扩展了 `.gitignore`，因此不要用该历史核验器给克隆仓库出新的 M6 成绩。常规源码验证使用 README 的 backend test、frontend build、Ruff 与 validate_handoff；完整交付复现须重新生成新的候选包和证据，保留旧报告。

初次推送后，普通后续同步可在审核变更后使用 `git push origin HEAD:main`。如果远端已有新提交，应先检查并整合，不能强制覆盖。公开源码不代表部署线上服务，也不引入生产认证或真实支付。

## 发布结果

首次源码提交 `1a5fd8f50dcb7178156cde7d6055604b5ffe349a` 已推送到远端main。GitHub API核对：仓库公开、默认分支main、提交与本地一致、许可证SPDX为MIT。1253个文件逐一确认暂存对象与已检查文件字节相同；1116个既有后端/前端/脚本/数据/评测文件与M6受验收版本哈希一致，四个冻结实现保持原样。文档/模拟数据检查PASS，发布文件未发现真实本地凭据。

本机Git/libcurl直连GitHub两次失败，使用一次性的loopback桥接将标准Git智能HTTP协议通过可用的Python HTTPS转发到原GitHub仓库，未强制推送、未修改系统网络或TLS设置。临时服务完成后关闭；只在内存使用现有Git凭据。仓库origin仍为标准HTTPS地址，后续可在可用网络中正常Git同步。发布记录通过后续文档提交同步。
