"""多点坐标选择相关文案。"""

MULTI_COORDINATE_BUTTON_TEXT = "划线获取路径"
MULTI_COORDINATE_PLACEHOLDER = "每行一个坐标: x,y\n如: 100,100"

MULTI_COORDINATE_EMPTY_HINT_LINES = (
    "按住左键划线，松开完成",
    "右键撤销上一个点",
    "Esc 或回车也可完成",
)

MULTI_COORDINATE_SELECTED_HINT_LINES = (
    "继续划线，或双击/回车完成",
    "右键撤销上一个点",
)

MULTI_COORDINATE_DRAWING_HINT = "松开鼠标完成路径"

ROUTE_SAMPLE_DISTANCE_PX = 8


def format_multi_coordinate_selected_text(count: int) -> str:
    return f"已选择 {count} 个坐标点"


def overlay_point_distance_sq(first, second) -> int:
    dx = int(second.x()) - int(first.x())
    dy = int(second.y()) - int(first.y())
    return dx * dx + dy * dy


def should_sample_route_point(last_overlay_pos, new_overlay_pos, min_distance: int = ROUTE_SAMPLE_DISTANCE_PX) -> bool:
    if last_overlay_pos is None:
        return True
    threshold = int(min_distance) * int(min_distance)
    return overlay_point_distance_sq(last_overlay_pos, new_overlay_pos) >= threshold


def should_finish_route_on_release(*, point_count: int, stroke_moved: bool) -> bool:
    return bool(stroke_moved) and int(point_count) >= 2
