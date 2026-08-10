from app.api.projects import PORTRAIT_SETTING_FIELDS, _resolve_portrait_settings
from app.schemas.project import ProjectCreate


def test_portrait_setting_fields_include_every_create_field():
    expected_fields = {
        field_name
        for field_name in ProjectCreate.model_fields
        if field_name.startswith("portrait_")
    }

    assert set(PORTRAIT_SETTING_FIELDS) == expected_fields


def test_global_portrait_defaults_override_new_project_values():
    data = ProjectCreate(title="测试", topic="测试主题")
    defaults = {
        "portrait_title_color": "#123456",
        "portrait_title_shadow_enabled": False,
        "portrait_title_bg_shape": "parallelogram",
        "portrait_sub_title_text": "全局副标题",
    }

    resolved = _resolve_portrait_settings(data, defaults)

    assert resolved["portrait_title_color"] == "#123456"
    assert resolved["portrait_title_shadow_enabled"] is False
    assert resolved["portrait_title_bg_shape"] == "parallelogram"
    assert resolved["portrait_sub_title_text"] == "全局副标题"
    assert resolved["portrait_bg_color"] == data.portrait_bg_color
