"""微信公众号(订阅号/服务号)发布客户端。

只覆盖到【建图文草稿】为止:获取 access_token → 上传封面/视频永久素材 →
新建草稿(draft/add)。不调用 freepublish(发布不可逆),发布这一步留给用户在
公众号后台手动完成。

说明:
- 公众号图文里【可播放的视频播放器】必须来自视频号/腾讯视频的 vid,官方 API
  没有途径把自有 mp4 嵌成播放器。这里的做法是把 mp4 传进【永久素材库】,用户
  在后台编辑草稿时手动拖入即可。
- 获取 token 要求调用方公网 IP 在公众号后台的 IP 白名单里(否则报 40164)。
- draft/add 等接口需要【已认证】的公众号,未认证会报 48001(api unauthorized)。

HTTP 调用集中在 `_get_json` / `_post_json` / `_post_file` 三个方法,便于测试时
注入假响应。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

WECHAT_API_BASE = "https://api.weixin.qq.com"

# 常见 errcode → 面向用户的中文提示。未列出的用 errcode+errmsg 原样透出。
_ERRCODE_HINTS = {
    40001: "AppSecret 错误或 access_token 失效,请检查公众号 AppSecret。",
    40013: "AppID 无效,请检查公众号 AppID。",
    40125: "AppSecret 无效,请检查公众号 AppSecret。",
    40164: "调用方公网 IP 不在公众号 IP 白名单里。请在公众号后台「设置与开发→基本配置→IP 白名单」加入你的公网 IP。",
    41001: "缺少 access_token。",
    45009: "接口调用超过频率/配额限制,请稍后再试。",
    48001: "接口未授权:该接口需要【已认证】的公众号(未认证的订阅号无发布/素材权限)。",
    40007: "media_id 无效(素材可能已过期或删除)。",
    53404: "公众号已被冻结,无法调用。",
    53500: "内容或封面命中安全策略被拦截。",
}


class WeChatAPIError(Exception):
    """微信接口返回业务错误(errcode != 0)或网络异常。"""

    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        hint = _ERRCODE_HINTS.get(errcode)
        msg = hint or f"微信接口错误 {errcode}: {errmsg}"
        super().__init__(msg)
        self.friendly = msg


@dataclass
class _TokenCache:
    token: str = ""
    expires_at: float = 0.0  # epoch 秒


# 进程内缓存,按 appid 存(access_token 有效期 ~7200s)。stable_token 允许在有效期内
# 反复获取同一个 token,不会像旧 token 接口那样让上一个失效,适合本地多次点击。
_token_cache: dict[str, _TokenCache] = {}


@dataclass
class WeChatArticle:
    """一条图文草稿。"""

    title: str
    content_html: str
    thumb_media_id: str
    author: str = ""
    digest: str = ""            # 摘要,留空则公众号自动截取正文前 54 字
    content_source_url: str = ""
    need_open_comment: int = 0
    only_fans_can_comment: int = 0

    def to_payload(self) -> dict:
        return {
            "title": self.title[:64],
            "author": self.author[:8] if self.author else "",
            "digest": self.digest[:120],
            "content": self.content_html,
            "content_source_url": self.content_source_url,
            "thumb_media_id": self.thumb_media_id,
            "need_open_comment": self.need_open_comment,
            "only_fans_can_comment": self.only_fans_can_comment,
        }


class WeChatClient:
    """公众号 API 薄封装。凭 appid + app_secret 构造。"""

    def __init__(self, appid: str, app_secret: str, timeout: float = 60.0):
        if not appid or not app_secret:
            raise ValueError("缺少公众号 AppID / AppSecret")
        self.appid = appid.strip()
        self.app_secret = app_secret.strip()
        self.timeout = timeout

    # ── HTTP 接缝(测试时可 monkeypatch) ──────────────────────────────
    async def _get_json(self, path: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{WECHAT_API_BASE}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post_json(self, path: str, params: dict, body: dict) -> dict:
        # ensure_ascii=False:公众号要求中文按 UTF-8 原文提交,不能转义成 \uXXXX
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{WECHAT_API_BASE}{path}", params=params, content=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            resp.raise_for_status()
            return resp.json()

    async def _post_file(self, path: str, params: dict,
                         file_path: Path, extra_form: dict | None = None) -> dict:
        files = {"media": (file_path.name, file_path.read_bytes())}
        async with httpx.AsyncClient(timeout=max(self.timeout, 180.0)) as client:
            resp = await client.post(
                f"{WECHAT_API_BASE}{path}", params=params,
                files=files, data=extra_form or {},
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _check(result: dict) -> dict:
        """errcode!=0 抛 WeChatAPIError。素材/草稿接口成功时不带 errcode。"""
        code = result.get("errcode", 0)
        if code and code != 0:
            raise WeChatAPIError(code, result.get("errmsg", ""))
        return result

    # ── 具体接口 ───────────────────────────────────────────────────────
    async def get_access_token(self, force_refresh: bool = False) -> str:
        cache = _token_cache.get(self.appid)
        now = time.time()
        if not force_refresh and cache and cache.token and cache.expires_at - 60 > now:
            return cache.token

        # 用 stable_token(在有效期内重复获取返回同一个,不会让旧 token 失效)
        result = await self._post_json(
            "/cgi-bin/stable_token", params={},
            body={
                "grant_type": "client_credential",
                "appid": self.appid,
                "secret": self.app_secret,
                "force_refresh": force_refresh,
            },
        )
        self._check(result)
        token = result.get("access_token", "")
        expires_in = int(result.get("expires_in", 7200))
        if not token:
            raise WeChatAPIError(-1, "未取到 access_token")
        _token_cache[self.appid] = _TokenCache(token=token, expires_at=now + expires_in)
        return token

    async def add_material_image(self, access_token: str, image_path: Path) -> str:
        """上传永久图片素材,返回 media_id(可作图文封面 thumb_media_id)。"""
        result = await self._post_file(
            "/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            file_path=image_path,
        )
        self._check(result)
        media_id = result.get("media_id")
        if not media_id:
            raise WeChatAPIError(-1, f"上传封面素材未返回 media_id: {result}")
        return media_id

    async def add_material_video(self, access_token: str, video_path: Path,
                                 title: str, introduction: str = "") -> str:
        """上传永久视频素材,返回 media_id。"""
        result = await self._post_file(
            "/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "video"},
            file_path=video_path,
            extra_form={"description": json.dumps(
                {"title": title[:64], "introduction": introduction[:120]},
                ensure_ascii=False,
            )},
        )
        self._check(result)
        media_id = result.get("media_id")
        if not media_id:
            raise WeChatAPIError(-1, f"上传视频素材未返回 media_id: {result}")
        return media_id

    async def add_draft(self, access_token: str, articles: list[WeChatArticle]) -> str:
        """新建图文草稿,返回草稿 media_id。"""
        result = await self._post_json(
            "/cgi-bin/draft/add",
            params={"access_token": access_token},
            body={"articles": [a.to_payload() for a in articles]},
        )
        self._check(result)
        media_id = result.get("media_id")
        if not media_id:
            raise WeChatAPIError(-1, f"建草稿未返回 media_id: {result}")
        return media_id


def article_text_to_html(text: str) -> str:
    """把纯文本/简单 Markdown 正文转成公众号图文可用的 HTML。

    只做最稳妥的转换:按空行分段,去掉 Markdown 标题的 # 号,每段包一个 <p>。
    公众号对 content 的 HTML 支持有限,保持简单最不容易出问题。
    """
    import html as _html

    blocks: list[str] = []
    for para in (text or "").replace("\r\n", "\n").split("\n\n"):
        line = para.strip()
        if not line:
            continue
        # 去掉行首的 markdown 标题标记 / 列表符号,保留文字
        stripped = "\n".join(
            l.lstrip("#").lstrip("-").lstrip("*").strip() for l in line.split("\n")
        ).strip()
        if not stripped:
            continue
        safe = _html.escape(stripped).replace("\n", "<br/>")
        blocks.append(
            f'<p style="margin:0 0 1em;line-height:1.75;font-size:16px;">{safe}</p>'
        )
    return "\n".join(blocks) or "<p></p>"
