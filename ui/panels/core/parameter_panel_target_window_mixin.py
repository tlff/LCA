from ..parameter_panel_support import *
from utils.window.window_binding_utils import (
    get_active_bound_windows,
    get_active_target_window_title,
    resolve_live_target_hwnd,
)

class ParameterPanelTargetWindowMixin:

    def _binding_host(self):
        return getattr(self, "main_window", None) or getattr(self, "parent_window", None)

    def _get_target_window_hwnd(self):
        """获取当前仍有效的目标窗口句柄，不沿用打开面板时缓存的失效值。"""
        try:
            logger.info("获取目标窗口句柄...")
            hwnd = resolve_live_target_hwnd(
                self._binding_host(),
                getattr(self, "target_window_hwnd", None),
            )
            if hwnd:
                self.target_window_hwnd = hwnd
                logger.info(f"当前目标窗口句柄: {hwnd}")
                return hwnd
            logger.warning("未找到任何绑定的窗口句柄")
            return None
        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None

    def _get_first_window_for_selection(self):
        """获取第一个窗口用于框选区域或坐标选择"""
        try:
            # 首先检查参数面板自身是否有目标窗口信息
            if hasattr(self, 'target_window_title') and self.target_window_title:
                return self.target_window_title

            # 向上查找主窗口，获取绑定的窗口列表
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:  # 最多向上查找10层
                # 检查是否有bound_windows属性（多窗口模式）
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        # 获取第一个启用的窗口
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                window_title = window_info.get('title')
                                if window_title:
                                    return window_title

                        # 如果没有启用的窗口，使用第一个窗口
                        first_window = bound_windows[0]
                        window_title = first_window.get('title')
                        if window_title:
                            return window_title

                # 检查是否有current_target_window_title属性（单窗口模式）
                if hasattr(current_widget, 'current_target_window_title'):
                    window_title = current_widget.current_target_window_title
                    if window_title:
                        return window_title

                # 检查是否有config属性
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if isinstance(config, dict):
                        target_window_title = get_active_target_window_title(config)
                        if target_window_title:
                            return target_window_title

                        bound_windows = get_active_bound_windows(config)
                        if bound_windows:
                            for window_info in bound_windows:
                                if window_info.get('enabled', True):
                                    window_title = window_info.get('title')
                                    if window_title:
                                        return window_title
                    elif config and hasattr(config, 'get'):
                        target_window_title = config.get('active_target_window_title') or config.get('target_window_title')
                        if target_window_title:
                            return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            return None
        except Exception as e:
            logger.error(f"获取第一个窗口失败: {e}")
            return None

    def _get_target_hwnd_with_info(self) -> tuple[Optional[int], Optional[str]]:
        """获取目标窗口句柄和窗口标题"""
        try:
            import win32gui

            logger.debug("开始获取目标窗口句柄和信息...")

            # 检查父窗口是否存在
            if not self.parent_window:
                logger.error("父窗口不存在")
                return None, None

            # 从绑定窗口列表获取第一个有效窗口（多窗口时使用第一个）
            if hasattr(self.parent_window, 'bound_windows'):
                bound_windows = self.parent_window.bound_windows
                logger.debug(f"找到绑定窗口列表，共 {len(bound_windows)} 个窗口")

                if bound_windows:
                    # 使用第一个窗口进行录制
                    first_window = bound_windows[0]
                    window_title = first_window.get('title', '未知')
                    hwnd = first_window.get('hwnd')
                    enabled = first_window.get('enabled', True)

                    logger.info(f"多窗口录制：使用第一个窗口 - {window_title} (句柄: {hwnd}, 启用: {enabled})")

                    if hwnd and win32gui.IsWindow(hwnd):
                        logger.info(f"选择录制窗口: {window_title} (句柄: {hwnd})")
                        return hwnd, window_title
                    else:
                        logger.warning(f"第一个窗口句柄已失效: {window_title} (句柄: {hwnd})")
            else:
                logger.debug("父窗口没有bound_windows属性")

            # 检查是否有current_target_hwnd
            if hasattr(self.parent_window, 'current_target_hwnd'):
                hwnd = self.parent_window.current_target_hwnd
                if hwnd and win32gui.IsWindow(hwnd):
                    window_title = win32gui.GetWindowText(hwnd)
                    logger.info(f"使用current_target_hwnd: {hwnd} ({window_title})")
                    return hwnd, window_title
                elif hwnd:
                    logger.warning(f"current_target_hwnd已失效: {hwnd}")
            else:
                logger.debug("父窗口没有current_target_hwnd属性")

            logger.error("未找到任何有效的绑定窗口句柄")
            return None, None

        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None, None

    def _get_target_hwnd(self) -> Optional[int]:
        """获取目标窗口句柄 - 直接使用全局设置中的绑定窗口"""
        try:
            import win32gui

            logger.debug("开始获取目标窗口句柄...")

            # 检查父窗口是否存在
            if not self.parent_window:
                logger.error("父窗口不存在")
                return None

            # 从绑定窗口列表获取第一个有效窗口
            if hasattr(self.parent_window, 'bound_windows'):
                bound_windows = self.parent_window.bound_windows
                logger.debug(f"找到绑定窗口列表，共 {len(bound_windows)} 个窗口")

                for i, window_info in enumerate(bound_windows):
                    window_title = window_info.get('title', '未知')
                    hwnd = window_info.get('hwnd')
                    enabled = window_info.get('enabled', True)

                    logger.debug(f"检查窗口 {i+1}: {window_title}, hwnd={hwnd}, enabled={enabled}")

                    if enabled and hwnd:
                        # 验证窗口句柄是否有效
                        if win32gui.IsWindow(hwnd):
                            logger.info(f"找到有效的绑定窗口: {window_title} (句柄: {hwnd})")
                            return hwnd
                        else:
                            logger.warning(f"绑定窗口句柄已失效: {window_title} (句柄: {hwnd})")

                # 如果没有启用的窗口，尝试使用第一个窗口
                if bound_windows:
                    first_window = bound_windows[0]
                    hwnd = first_window.get('hwnd')
                    if hwnd and win32gui.IsWindow(hwnd):
                        logger.info(f"使用第一个绑定窗口: {first_window.get('title', '未知')} (句柄: {hwnd})")
                        return hwnd
            else:
                logger.debug("父窗口没有bound_windows属性")

            # 检查是否有current_target_hwnd
            if hasattr(self.parent_window, 'current_target_hwnd'):
                hwnd = self.parent_window.current_target_hwnd
                if hwnd and win32gui.IsWindow(hwnd):
                    logger.info(f"使用current_target_hwnd: {hwnd}")
                    return hwnd
                elif hwnd:
                    logger.warning(f"current_target_hwnd已失效: {hwnd}")
            else:
                logger.debug("父窗口没有current_target_hwnd属性")

            logger.error("全局设置中没有有效的绑定窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            return None
