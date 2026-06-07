"""内置工具包 —— 存放 Haven 框架内置的工具实现。

此目录下的 .py 文件会被 BuiltinProvider 自动扫描。
只需定义一个 BaseTool 子类，无需修改任何配置文件。

添加新工具的步骤：
  1. 在此目录创建 ``your_tool.py``
  2. 定义一个继承自 ``HavenTool`` 或 ``BaseTool`` 的类
  3. 设置 name、description，实现 _run / _arun
  4. 重启 Haven 即可自动生效
"""
