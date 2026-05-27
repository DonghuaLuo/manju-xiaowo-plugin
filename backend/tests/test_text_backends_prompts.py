"""文本后端 prompt 常量测试。"""

from lib.text_backends.prompts import STYLE_ANALYSIS_PROMPT


def test_style_analysis_prompt_requires_accurate_chinese_style_output():
    assert "简体中文" in STYLE_ANALYSIS_PROMPT
    assert "准确优先" in STYLE_ANALYSIS_PROMPT
    assert "画风：" in STYLE_ANALYSIS_PROMPT
    assert "不要描述人物、物体、场景事件" in STYLE_ANALYSIS_PROMPT

    for keyword in ("光线", "色彩", "渲染", "镜头", "构图", "纹理", "氛围"):
        assert keyword in STYLE_ANALYSIS_PROMPT

    assert "不要猜测" in STYLE_ANALYSIS_PROMPT
    assert "国际通用技术术语" in STYLE_ANALYSIS_PROMPT
