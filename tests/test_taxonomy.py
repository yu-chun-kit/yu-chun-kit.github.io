from chatblog.taxonomy import Tag, load_taxonomy


def answers(**overrides):
    base = {
        "domain": {"type": "choice", "choice": "technology", "probabilities": {"technology": 0.9}},
        "subdomain": {"type": "choice", "choice": "ai_llm", "probabilities": {"ai_llm": 0.8}},
        "concept": {"type": "choice", "choice": "jev", "probabilities": {"jev": 0.7}},
        "genre": {"type": "choice", "choice": "analysis", "probabilities": {"analysis": 0.6}},
        "depth": {"type": "score", "score": 3.0, "confidence": 0.5},
        "language": {"type": "choice", "choice": "zh", "probabilities": {"zh": 0.95}},
        "sensitivity": {"type": "choice", "choice": "normal", "probabilities": {"normal": 0.99}},
        "has_code": {"type": "noul", "noul": 0.62},
        "is_series": {"type": "noul", "noul": 0.1},
        "publishable": {"type": "noul", "noul": 0.8},
        "has_private_info": {"type": "noul", "noul": 0.05},
    }
    base.update(overrides)
    return base


def test_questions_cover_every_dimension():
    taxonomy = load_taxonomy()
    questions = taxonomy.questions()
    assert set(questions) == {
        "domain",
        "subdomain",
        "concept",
        "genre",
        "depth",
        "language",
        "sensitivity",
        "has_code",
        "is_series",
        "publishable",
        "has_private_info",
    }
    assert questions["domain"]["type"] == "choice"
    assert "technology" in questions["domain"]["criteria"]
    assert questions["depth"]["type"] == "score"
    assert len(questions["depth"]["criteria"]) == 5
    assert questions["has_code"] == {
        "type": "noul",
        "instructions": questions["has_code"]["instructions"],
    }
    assert len(questions["concept"]["criteria"]) <= 255
    assert len(questions["subdomain"]["criteria"]) <= 255


def test_compose_maps_ids_to_labels_and_thresholds_flags():
    tags = load_taxonomy().compose(answers())
    names = [tag.name for tag in tags]
    assert names[0] == "技術程式"
    assert "AI/LLM" in names
    assert "Jev" in names
    assert "分析" in names
    assert "深度 4/5" in names
    assert "中文" in names
    assert "含程式碼" in names
    assert "適合發佈" in names
    assert "連載/專案" not in names
    assert "含私隱" not in names
    assert "一般" not in names


def test_compose_drops_subdomain_from_another_domain():
    tags = load_taxonomy().compose(
        answers(domain={"type": "choice", "choice": "philosophy", "confidence": 0.9})
    )
    names = [tag.name for tag in tags]
    assert names[0] == "哲學思想"
    assert "AI/LLM" not in names


def test_compose_skips_none_concept():
    tags = load_taxonomy().compose(
        answers(concept={"type": "choice", "choice": "none", "confidence": 0.9})
    )
    assert "（無明顯主題）" not in [tag.name for tag in tags]


def test_rules_fallback_produces_a_domain_and_language():
    taxonomy = load_taxonomy()
    tags = taxonomy.rules("我想用 hexo 部署部落格，docker 容器一直重啟", "Hexo 部署問題")
    names = [tag.name for tag in tags]
    assert names[0] == "技術程式"
    assert "中文" in names
    assert any(name.startswith("深度 ") for name in names)


def test_post_tags_are_coarse():
    taxonomy = load_taxonomy()
    tags = [
        Tag("技術程式", "domain", 0.9),
        Tag("AI/LLM", "subdomain", 0.8),
        Tag("Jev", "concept", 0.7),
    ]
    assert taxonomy.post_tags(tags, "gemini") == ["AI对话", "Gemini", "技術程式"]
    assert taxonomy.post_tags([], "openwebui") == ["AI对话", "OpenWebUI"]


def test_additive_taxonomy_file_extends_concepts(tmp_path):
    import json

    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "concepts": {
                    "my_topic": {
                        "label": "我的主題",
                        "description": "custom",
                        "parent": "technology",
                        "keywords": ["我的主題"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(path)
    assert taxonomy.option("concept", "my_topic").label == "我的主題"
    # Built-ins survive an additive file.
    assert taxonomy.option("concept", "jev") is not None
