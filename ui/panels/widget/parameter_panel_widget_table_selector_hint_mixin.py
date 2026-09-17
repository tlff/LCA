from .parameter_panel_widget_table_selector_hint_conditions_mixin import (
    ParameterPanelWidgetTableSelectorHintConditionsMixin,
)
from .parameter_panel_widget_table_selector_hint_dispatch_mixin import (
    ParameterPanelWidgetTableSelectorHintDispatchMixin,
)
from .parameter_panel_widget_table_selector_hint_shared_mixin import (
    ParameterPanelWidgetTableSelectorHintSharedMixin,
)


class ParameterPanelWidgetTableSelectorHintMixin(
    ParameterPanelWidgetTableSelectorHintDispatchMixin,
    ParameterPanelWidgetTableSelectorHintSharedMixin,
    ParameterPanelWidgetTableSelectorHintConditionsMixin,
):
    pass
