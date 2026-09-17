"""导出组件包。

保持导出算法模块可在无 Qt 的运行时（例如脚本校验器、CI）导入；
只有访问对话框类时才加载 PySide6。
"""

__all__ = ["StandaloneExportDialog"]


def __getattr__(name: str):
    if name == "StandaloneExportDialog":
        from .export_dialog import StandaloneExportDialog

        return StandaloneExportDialog
    raise AttributeError(name)
