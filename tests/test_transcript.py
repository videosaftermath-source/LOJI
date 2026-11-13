from core.transcript import FILE_LIMIT, Build, Fit


def msg(i, text, data=None):
    att = [{"name": "a.png", "url": "u", "type": "image/jpeg", "data": data}] if data else []
    return {"author": f"user{i}", "author_id": i, "bot": False, "avatar": "", "ts": 1000 + i * 600, "content": text, "embeds": [], "attachments": att}


def test_escapes_and_groups():
    html = Build({"title": "reporte-001", "reason": "<b>ok</b>"}, [msg(1, "<script>alert(1)</script>"), msg(2, "hola")])
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "&lt;b&gt;ok" in html
    assert html.count("class='m'") == 2


def test_fit_drops_images_when_too_big():
    big = "A" * (FILE_LIMIT // 3)
    msgs = [msg(i, "x", big) for i in range(5)]
    data = Fit({"title": "t"}, msgs)
    assert len(data) <= FILE_LIMIT and b"a.png" in data
