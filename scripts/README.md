# 数据库初始化

1. 安装项目依赖：

   ```powershell
   pip install -r requirements.txt
   ```

2. 创建本地环境配置文件并编辑 PostgreSQL 相关配置：

   ```powershell
   Copy-Item .env.example .env
   ```

3. 确保 PostgreSQL 16 正在运行，并且 `DATABASE_URL` 中指定的数据库已存在。该脚本会创建数据表，但不会创建 PostgreSQL 数据库或用户。

4. 在项目根目录下执行：

   ```powershell
   python scripts/create_tables.py
   ```

该命令具有幂等性和追加性。它会基于 `app/db/models.py` 创建业务数据表，然后调用 LangGraph 的 `PostgresSaver.setup()` 来创建其检查点（checkpoint）相关的数据表。该命令不会删除或修改已有的数据表。
