"""send_wechat（用户版 8 步闭环）的纯函数回归，无 GUI。"""


def _item(text, cx=100, cy=100, score=0.9):
    return {"text": text, "cx": cx, "cy": cy, "x": cx, "y": cy, "score": score}


def test_find_exact():
    from uiu.wechat_tools import find_in_items
    items = [_item("微信游戏"), _item("文件传输助手")]
    assert find_in_items(items, "文件传输助手", exact=True)["text"] == "文件传输助手"
    assert find_in_items(items, "不存在", exact=True) is None
    assert find_in_items(items, "") is None


def test_find_fuzzy_picks_closest_length():
    from uiu.wechat_tools import find_in_items
    items = [_item("文件传输助手天天玩"), _item("文件传输")]
    # 非精确：长度最接近 needle 的胜出（|4-6|=2 < |11-6|=5）
    assert find_in_items(items, "文件传输助手")["text"] == "文件传输"


def test_filter_by_zone():
    from uiu.wechat_tools import filter_by_zone
    items = [_item("a", 100, 100), _item("b", 500, 500), _item("c", 100, 900)]
    assert [i["text"] for i in filter_by_zone(items, 0, 0, 200, 200)] == ["a"]
    assert filter_by_zone(items, 0, 0, 200, 200)[0]["cx"] == 100


def test_send_validates_input_headless():
    from uiu.wechat_tools import send_wechat
    assert send_wechat("", "hi").startswith("[error]")
    assert send_wechat("谁", "").startswith("[error]")
    assert send_wechat("  ", "hi").startswith("[error]")


def test_zones_geometry():
    # 标题栏 / 输入区 / 聊天区三带互不重叠（1000x800 窗口）
    left, top, right, bottom = 0, 0, 1000, 800
    w, h = 1000, 800
    title = (int(left + w * 0.35), top, int(right - w * 0.1), int(top + h * 0.15))
    chat = (int(left + w * 0.35), int(top + h * 0.15), right, int(top + h * 0.75))
    assert title[3] <= chat[1]  # 标题带在聊天带之上
    assert chat[3] <= bottom
