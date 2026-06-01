import yaml

from lib.prompt_utils import (
    VideoPromptPolicy,
    build_speaker_profiles,
    image_prompt_to_yaml,
    is_structured_image_prompt,
    is_structured_video_prompt,
    validate_camera_motion,
    validate_shot_type,
    video_prompt_to_yaml,
)


class TestPromptUtils:
    def test_image_prompt_to_yaml_keeps_expected_shape(self):
        data = {
            "scene": "夜雨中的街道",
            "composition": {
                "shot_type": "Medium Shot",
                "lighting": "路灯暖光",
                "ambiance": "薄雾",
            },
        }

        text = image_prompt_to_yaml(data, "Anime")
        parsed = yaml.safe_load(text)
        assert parsed["Style"] == "Anime"
        assert parsed["Scene"] == "夜雨中的街道"
        assert parsed["Composition"]["shot_type"] == "Medium Shot"

    def test_video_prompt_to_yaml_includes_dialogue_conditionally(self):
        with_dialogue = {
            "action": "抬头观察",
            "camera_motion": "Static",
            "ambiance_audio": "雨声",
            "dialogue": [{"speaker": "姜月茴", "line": "有人吗", "emotion": "紧张", "screen_position": "left"}],
        }
        without_dialogue = {
            "action": "快步前进",
            "camera_motion": "Pan Left",
            "ambiance_audio": "脚步声",
            "dialogue": [],
        }

        parsed_a = yaml.safe_load(video_prompt_to_yaml(with_dialogue))
        parsed_b = yaml.safe_load(video_prompt_to_yaml(without_dialogue))

        assert parsed_a["Action"] == "抬头观察"
        assert parsed_a["Dialogue"][0]["Speaker"] == "姜月茴"
        assert parsed_a["Dialogue"][0]["Emotion"] == "紧张"
        assert parsed_a["Dialogue"][0]["Screen_Position"] == "left"
        assert "Speaking_Rules" in parsed_a
        assert "Dialogue" not in parsed_b

    def test_video_prompt_to_yaml_adds_speaker_profiles(self):
        prompt = {
            "action": "小月抬头说话，阿城保持沉默",
            "camera_motion": "Static",
            "ambiance_audio": "风声",
            "dialogue": [{"speaker": "小月", "line": "快走", "screen_position": "left"}],
        }
        project = {"characters": {"小月": {"voice_style": "清亮，语速偏快"}, "阿城": {"voice_style": "低沉"}}}
        item = {"characters_in_scene": ["小月", "阿城"]}

        profiles = build_speaker_profiles(project, item, dialogue=prompt["dialogue"])
        parsed = yaml.safe_load(video_prompt_to_yaml(prompt, speaker_profiles=profiles))

        assert parsed["Visible_Characters"][0]["Name"] == "小月"
        assert parsed["Visible_Characters"][0]["Voice_Style"] == "清亮，语速偏快"
        assert parsed["Visible_Characters"][0]["Screen_Position"] == "left"
        assert parsed["Visible_Characters"][1]["Name"] == "阿城"
        assert "阿城保持闭嘴不说话" in parsed["Dialogue"][0]["Mouth_Cue"]

    def test_video_prompt_to_yaml_keeps_only_motion_relevant_optional_fields(self):
        prompt = {
            "action": "主角向前一步",
            "camera_motion": "Zoom In",
            "subject_motion": "手指轻微颤抖",
            "emotion": "压抑愤怒",
            "environment_motion": "窗帘被风吹动",
            "avoid": "不要改变角色服装",
            "ambiance_audio": "",
            "dialogue": [],
        }

        parsed = yaml.safe_load(video_prompt_to_yaml(prompt))

        assert parsed["Subject_Motion"] == "手指轻微颤抖"
        assert parsed["Emotion"] == "压抑愤怒"
        assert parsed["Environment_Motion"] == "窗帘被风吹动"
        assert parsed["Avoid"] == "不要改变角色服装"
        assert "Ambiance_Audio" not in parsed

    def test_video_prompt_policy_omits_audio_hints_when_model_has_no_audio(self):
        prompt = {
            "action": "小月抬头说话",
            "camera_motion": "Static",
            "ambiance_audio": "风声",
            "dialogue": [{"speaker": "小月", "line": "快走", "screen_position": "left"}],
        }
        project = {"characters": {"小月": {"voice_style": "清亮，语速偏快"}}}
        item = {"characters_in_scene": ["小月"]}

        profiles = build_speaker_profiles(project, item, dialogue=prompt["dialogue"])
        parsed = yaml.safe_load(
            video_prompt_to_yaml(
                prompt,
                speaker_profiles=profiles,
                policy=VideoPromptPolicy(supports_generated_audio=False),
            )
        )

        assert "Voice_Style" not in parsed["Visible_Characters"][0]
        assert "Mouth_Cue" not in parsed["Dialogue"][0]
        assert "Speaking_Rules" not in parsed

    def test_video_prompt_policy_compacts_visible_characters_and_voice_style(self):
        prompt = {
            "action": "多人在大厅里对话",
            "camera_motion": "Static",
            "ambiance_audio": "大厅回声",
            "dialogue": [{"speaker": "小月", "line": "安静", "screen_position": "center"}],
        }
        project = {
            "characters": {
                "小月": {"voice_style": "清亮、克制、语速偏快，带一点疲惫但仍然坚定。" * 4},
                "阿城": {"voice_style": "低沉"},
                "白璃": {"voice_style": "柔和"},
                "墨川": {"voice_style": "沙哑"},
            }
        }
        item = {"characters_in_scene": ["小月", "阿城", "白璃", "墨川"]}

        profiles = build_speaker_profiles(project, item, dialogue=prompt["dialogue"])
        parsed = yaml.safe_load(
            video_prompt_to_yaml(
                prompt,
                speaker_profiles=profiles,
                policy=VideoPromptPolicy(compact=True, max_visible_characters=2, voice_style_max_chars=20),
            )
        )

        assert [p["Name"] for p in parsed["Visible_Characters"]] == ["小月", "阿城"]
        assert parsed["Visible_Characters"][0]["Voice_Style"].endswith("...")
        assert "其他可见角色" in parsed["Dialogue"][0]["Mouth_Cue"] or "阿城保持闭嘴" in parsed["Dialogue"][0]["Mouth_Cue"]

    def test_structured_checks(self):
        assert is_structured_image_prompt({"scene": "x"})
        assert not is_structured_image_prompt("text")
        assert is_structured_video_prompt({"action": "x"})
        assert not is_structured_video_prompt([])

    def test_validators(self):
        assert validate_shot_type("Close-up")
        assert not validate_shot_type("Bad Shot")
        assert validate_camera_motion("Zoom In")
        assert not validate_camera_motion("Teleport")
