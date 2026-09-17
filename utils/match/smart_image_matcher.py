#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单模板匹配器
"""

import logging
import cv2
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""
    found: bool
    confidence: float
    center: Optional[Tuple[int, int]] = None
    location: Optional[Tuple[int, int, int, int]] = None
    method: str = "template"


def normalize_match_image(image: Optional[np.ndarray], mode: str = "彩色") -> Optional[np.ndarray]:
    """Normalize template-match inputs without discarding color channels."""
    if image is None or (not isinstance(image, np.ndarray)) or image.size == 0:
        return None

    try:
        mode_key = str(mode or "彩色").strip().casefold()
        gray = mode_key in {"灰度", "gray", "grey", "grayscale"}
        if image.ndim == 2:
            return np.ascontiguousarray(image if gray else cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_GRAY2BGR))

        if image.ndim != 3:
            return None

        channels = int(image.shape[2])
        if channels == 3:
            value = np.ascontiguousarray(image)
            return cv2.cvtColor(value, cv2.COLOR_BGR2GRAY) if gray else value
        if channels == 4:
            value = cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_BGRA2BGR)
            return cv2.cvtColor(value, cv2.COLOR_BGR2GRAY) if gray else value
        if channels == 1:
            return cv2.cvtColor(np.ascontiguousarray(image[:, :, 0]), cv2.COLOR_GRAY2BGR)
        return None
    except Exception:
        return None


def _rotate_template(template: np.ndarray, angle: float) -> np.ndarray:
    if abs(float(angle)) < 1e-6:
        return template
    h, w = template.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
    cos_v, sin_v = abs(matrix[0, 0]), abs(matrix[0, 1])
    nw, nh = int(round(h * sin_v + w * cos_v)), int(round(h * cos_v + w * sin_v))
    matrix[0, 2] += nw / 2.0 - center[0]
    matrix[1, 2] += nh / 2.0 - center[1]
    border = 0 if template.ndim == 2 else (0, 0, 0)
    return cv2.warpAffine(template, matrix, (max(1, nw), max(1, nh)), borderValue=border)


def _angles(value) -> list:
    if value is None or value == "":
        return [0.0]
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    result = []
    for item in raw:
        try:
            angle = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("旋转角度必须是数字") from exc
        if not np.isfinite(angle) or angle < -180 or angle > 180:
            raise ValueError("旋转角度必须在 -180 到 180 之间")
        if all(abs(angle - old) > 1e-6 for old in result):
            result.append(angle)
    return result[:21] or [0.0]


def match_template(screenshot: np.ndarray,
                   template: np.ndarray,
                   confidence: float = 0.8,
                   roi: Optional[Tuple[int, int, int, int]] = None,
                   mode: str = "彩色",
                   rotation=0) -> MatchResult:
    """
    简单模板匹配

    Args:
        screenshot: 截图图像
        template: 模板图像
        confidence: 置信度阈值(0-1)
        roi: 感兴趣区域 (x, y, w, h)

    Returns:
        MatchResult: 匹配结果
    """
    # 参数验证
    if screenshot is None or template is None:
        return MatchResult(found=False, confidence=0.0, method="error")

    if screenshot.size == 0 or template.size == 0:
        return MatchResult(found=False, confidence=0.0, method="error")

    # ROI处理
    search_img = screenshot
    roi_offset = (0, 0)
    if roi is not None:
        x, y, w, h = roi
        if x >= 0 and y >= 0 and x + w <= screenshot.shape[1] and y + h <= screenshot.shape[0]:
            search_img = screenshot[y:y+h, x:x+w]
            roi_offset = (x, y)

    try:
        search_match_image = normalize_match_image(search_img, mode)
        template_base = normalize_match_image(template, mode)
        if template_base is None:
            return MatchResult(found=False, confidence=0.0, method="error")

        best = None
        for angle in _angles(rotation):
            template_match_image = _rotate_template(template_base, angle)
            if search_match_image.shape[0] < template_match_image.shape[0] or search_match_image.shape[1] < template_match_image.shape[1]:
                continue
            result = cv2.matchTemplate(search_match_image, template_match_image, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if best is None or max_val > best[0]:
                best = (max_val, max_loc, template_match_image)
        if best is None:
            return MatchResult(found=False, confidence=0.0, method="size_error")
        max_val, max_loc, template_match_image = best
        if search_match_image is None:
            return MatchResult(found=False, confidence=0.0, method="error")

        # 尺寸检查
        if (
            search_match_image.shape[0] < template_match_image.shape[0]
            or search_match_image.shape[1] < template_match_image.shape[1]
        ):
            return MatchResult(found=False, confidence=0.0, method="size_error")

        # 执行匹配
        # 检查置信度
        if max_val >= confidence:
            template_h, template_w = template_match_image.shape[:2]
            final_x = max_loc[0] + roi_offset[0]
            final_y = max_loc[1] + roi_offset[1]
            center_x = final_x + template_w // 2
            center_y = final_y + template_h // 2

            return MatchResult(
                found=True,
                confidence=float(max_val),
                center=(center_x, center_y),
                location=(final_x, final_y, template_w, template_h),
                method="template"
            )
        else:
            return MatchResult(
                found=False,
                confidence=float(max_val),
                method="template"
            )

    except Exception as e:
        logger.error(f"模板匹配失败: {e}")
        return MatchResult(found=False, confidence=0.0, method="error")


def match_template_all(
    screenshot: np.ndarray,
    template: np.ndarray,
    confidence: float = 0.8,
    roi: Optional[Tuple[int, int, int, int]] = None,
    max_count: int = 20,
    mode: str = "彩色",
    rotation=0,
) -> list:
    """同一模板的全部命中，按分数从高到低，邻近峰会合并。"""
    first = match_template(screenshot, template, confidence, roi, mode=mode, rotation=rotation)
    if not first.found:
        return []
    search_match_image = normalize_match_image(screenshot if roi is None else screenshot[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]], mode)
    template_match_image = normalize_match_image(template, mode)
    if search_match_image is None or template_match_image is None:
        return [first]
    try:
        # 多角度时逐角度收集，再按分数合并相邻峰。
        angle_list = _angles(rotation)
        heats = []
        for angle in angle_list:
            rotated = _rotate_template(template_match_image, angle)
            if rotated.shape[0] <= search_match_image.shape[0] and rotated.shape[1] <= search_match_image.shape[1]:
                heats.append((cv2.matchTemplate(search_match_image, rotated, cv2.TM_CCOEFF_NORMED), rotated))
        if not heats:
            return [first]
        heat, template_match_image = max(heats, key=lambda item: float(cv2.minMaxLoc(item[0])[1]))
    except Exception:
        return [first]
    template_h, template_w = template_match_image.shape[:2]
    roi_x = int(roi[0]) if roi is not None else 0
    roi_y = int(roi[1]) if roi is not None else 0
    gap = max(8, min(template_w, template_h) // 2)
    found = []
    work = heat.copy()
    limit = max(1, min(int(max_count or 20), 50))
    while len(found) < limit:
        _, max_val, _, max_loc = cv2.minMaxLoc(work)
        if max_val < confidence:
            break
        left = int(max_loc[0]) + roi_x
        top = int(max_loc[1]) + roi_y
        found.append(
            MatchResult(
                found=True,
                confidence=float(max_val),
                center=(left + template_w // 2, top + template_h // 2),
                location=(left, top, template_w, template_h),
                method="template",
            )
        )
        x0 = max(0, int(max_loc[0]) - gap)
        y0 = max(0, int(max_loc[1]) - gap)
        x1 = min(work.shape[1], int(max_loc[0]) + gap)
        y1 = min(work.shape[0], int(max_loc[1]) + gap)
        work[y0:y1, x0:x1] = 0
    return found
