"""公众号发布客户端:orchestration + 错误码映射(不打真实微信接口)。

WeChatClient 的三个 HTTP 接缝被替换成假响应,验证:token 缓存、素材/草稿调用
顺序、以及 errcode → 友好中文提示的映射。
"""

import time

import pytest

from app.services.publishers import wechat_publisher as wp
from app.services.publishers.wechat_publisher import (
    WeChatAPIError,
    WeChatArticle,
    WeChatClient,
    article_text_to_html,
)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    wp._token_cache.clear()
    yield
    wp._token_cache.clear()


class FakeClient(WeChatClient):
    """记录调用、按脚本返回假响应。"""

    def __init__(self, scripts):
        super().__init__("appid_x", "secret_y")
        self.scripts = scripts          # {path: response dict}
        self.calls = []

    async def _get_json(self, path, params):
        self.calls.append(("GET", path))
        return self.scripts[path]

    async def _post_json(self, path, params, body):
        self.calls.append(("POST_JSON", path, body))
        return self.scripts[path]

    async def _post_file(self, path, params, file_path, extra_form=None):
        self.calls.append(("POST_FILE", path, params.get("type")))
        return self.scripts[path]


@pytest.mark.asyncio
async def test_get_token_caches():
    c = FakeClient({"/cgi-bin/stable_token": {"access_token": "TOK", "expires_in": 7200}})
    t1 = await c.get_access_token()
    t2 = await c.get_access_token()
    assert t1 == t2 == "TOK"
    # 第二次命中缓存,不再打 stable_token
    token_calls = [x for x in c.calls if x[1] == "/cgi-bin/stable_token"]
    assert len(token_calls) == 1


@pytest.mark.asyncio
async def test_expired_token_refetches():
    c = FakeClient({"/cgi-bin/stable_token": {"access_token": "TOK", "expires_in": 7200}})
    await c.get_access_token()
    # 手动把缓存改成已过期
    wp._token_cache[c.appid].expires_at = time.time() - 1
    await c.get_access_token()
    token_calls = [x for x in c.calls if x[1] == "/cgi-bin/stable_token"]
    assert len(token_calls) == 2


@pytest.mark.asyncio
async def test_ip_whitelist_error_is_friendly():
    c = FakeClient({"/cgi-bin/stable_token": {"errcode": 40164, "errmsg": "invalid ip"}})
    with pytest.raises(WeChatAPIError) as ei:
        await c.get_access_token()
    assert ei.value.errcode == 40164
    assert "IP 白名单" in ei.value.friendly


@pytest.mark.asyncio
async def test_unauthorized_account_error_is_friendly():
    c = FakeClient({
        "/cgi-bin/stable_token": {"access_token": "TOK", "expires_in": 7200},
        "/cgi-bin/draft/add": {"errcode": 48001, "errmsg": "api unauthorized"},
    })
    tok = await c.get_access_token()
    with pytest.raises(WeChatAPIError) as ei:
        await c.add_draft(tok, [WeChatArticle(title="t", content_html="<p>x</p>", thumb_media_id="m")])
    assert "认证" in ei.value.friendly


@pytest.mark.asyncio
async def test_full_draft_flow_order_and_ids():
    c = FakeClient({
        "/cgi-bin/stable_token": {"access_token": "TOK", "expires_in": 7200},
        "/cgi-bin/material/add_material": {"media_id": "MAT"},
        "/cgi-bin/draft/add": {"media_id": "DRAFT"},
    })
    tok = await c.get_access_token()
    thumb = await c.add_material_image(tok, __import__("pathlib").Path(__file__))
    draft = await c.add_draft(tok, [WeChatArticle(
        title="标题", content_html="<p>正文</p>", thumb_media_id=thumb, digest="摘要")])
    assert thumb == "MAT"
    assert draft == "DRAFT"
    # 草稿请求体里带上了 thumb_media_id 和中文标题
    draft_call = [x for x in c.calls if x[1] == "/cgi-bin/draft/add"][0]
    body = draft_call[2]
    assert body["articles"][0]["thumb_media_id"] == "MAT"
    assert body["articles"][0]["title"] == "标题"


def test_article_html_paragraphs_and_escaping():
    html = article_text_to_html("# 标题行\n\n第一段 <b>不该生效</b>\n\n第二段")
    assert html.count("<p") == 3  # 标题行也成一段(去掉 #)
    assert "&lt;b&gt;" in html   # HTML 转义,避免注入
    assert "<p></p>" not in html


def test_article_html_empty():
    assert article_text_to_html("") == "<p></p>"
    assert article_text_to_html("   \n\n  ") == "<p></p>"
