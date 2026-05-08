# 数据库备份工具

一个基于 Python `tkinter` 的桌面备份工具，适合快速配置 SQL Server 或 MySQL 连接并执行数据库备份。

## 功能

- 图形化界面
- SQL Server / MySQL 连接配置
- Windows 认证 / SQL Server 认证
- 数据库连接测试
- 自动读取数据库列表
- 一键备份数据库
- 定时自动备份
- 最小化到系统托盘后台运行
- 开机自动启动
- 开机后静默最小化运行
- 托盘消息通知
- 日志实时显示
- 本地保存配置到 `config.json`
- 支持打包为 Windows `exe`

## 环境要求

- Windows
- Python 3.10+
- SQL Server：SQL Server ODBC Driver 17 或 18
- MySQL：MySQL 客户端工具，需可在命令行执行 `mysqldump`

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动方式

```bash
python app.py
```

## 托盘运行

- 点击“最小化到托盘”后，主窗口会隐藏到系统托盘继续后台运行。
- 勾选“关闭窗口时最小化到托盘”后，点击右上角关闭按钮不会退出程序，而是转入托盘。
- 托盘菜单支持“显示窗口”、“立即备份”和“退出程序”。
- 可开启托盘通知，在连接成功、备份完成、备份失败等场景弹出提醒。
- 定时备份在托盘后台运行时同样有效。

## 开机自启动

- 勾选“开机自动启动程序”后，程序会写入当前用户的 Windows 启动项。
- 勾选“开机后静默最小化到托盘”后，配合开机自启动使用时，程序启动后不会弹出主窗口，而是直接进入系统托盘后台运行。
- 该设置保存在注册表 `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`。
- 打包成 `exe` 后，自启动会直接拉起 `exe`；脚本模式下会使用当前 Python 解释器启动 `app.py`。

## 使用说明

1. 选择数据库类型：`SQL Server` 或 `MySQL`。
2. 填写服务器/主机、端口和认证信息。
3. 点击“读取数据库”获取数据库列表。
4. 选择需要备份的数据库。
5. 设置备份目录和备份文件名。
6. 点击“测试连接”确认数据库可访问。
7. 点击“开始备份”执行备份。

如果不填写备份文件名，SQL Server 会自动按 `数据库名_时间戳.bak` 生成，MySQL 会自动按 `数据库名_时间戳.sql` 生成。

## 定时备份

- 勾选“启用定时备份”后可开启后台自动备份。
- 支持“每天固定时间”与“按间隔分钟”两种模式。
- 每天固定时间示例：`02:00`
- 按间隔分钟示例：`30`、`60`、`120`
- 程序需要保持运行，后台才会按计划自动执行备份。
- 定时备份会复用当前界面的数据库配置和备份配置。

## 打包 EXE

方式一：直接执行脚本

```bat
build_exe.bat
```

方式二：手动执行

```bash
pip install -r requirements.txt
pyinstaller --clean --noconfirm sql_backup_tool.spec
```

生成后的可执行文件位于：

```text
dist\SQLServerBackupTool.exe
```

打包后的 `exe` 会默认在自身所在目录读取和保存 `config.json`。

## 配置文件

程序会将界面中的配置保存到当前目录下的 `config.json`。

## 注意事项

- 执行 SQL Server 备份的账号需要具备 SQL Server 备份权限。
- 执行 MySQL 备份的账号需要具备读取目标库、表、视图、触发器、事件和存储过程的权限。
- 如果遇到 SQL Server 连接失败，请确认 SQL Server 已开启 TCP/IP、端口可访问，并已安装 ODBC 驱动。
- 如果遇到 MySQL 备份失败，请确认 `mysqldump` 已安装并加入 `PATH`。
