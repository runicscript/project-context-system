"""飞书开放 API 的最小封装：拿 token、列记录、增改记录、列字段。

只封装本项目用到的几个接口，出错时给出人类能看懂的提示。
"""

from __future__ import annotations

import time

import requests

from writeback import flat_text, link_ids, parse_snapshot, url_text  # noqa: F401 纯函数统一定义在 writeback.py

__all__ = ["API_BASE", "TIMEOUT", "FeishuError", "FeishuClient",
           "flat_text", "url_text", "link_ids", "parse_snapshot"]

API_BASE = "https://open.feishu.cn/open-apis"
TIMEOUT = 15


class FeishuError(RuntimeError):
    """飞书接口返回错误时抛出，message 里带官方 code 和提示。"""


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, base_token: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_token = base_token
        self._token: str | None = None
        self._expire_at = 0.0

    # ---- 认证 ----

    def _tenant_token(self) -> str:
        """获取 tenant_access_token，带本地缓存（官方有效期约 2 小时）。"""
        if self._token and time.time() < self._expire_at - 120:
            return self._token
        resp = requests.post(
            f"{API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=TIMEOUT,
        ).json()
        if resp.get("code") != 0:
            raise FeishuError(
                f"获取 tenant_access_token 失败（code={resp.get('code')}）："
                f"{resp.get('msg')}。请检查 .env 里的 APP_ID / APP_SECRET，"
                f"以及应用是否已发布生效。"
            )
        self._token = resp["tenant_access_token"]
        self._expire_at = time.time() + int(resp.get("expire", 7200))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._tenant_token()}"}

    def _check(self, body: dict, action: str) -> dict:
        if body.get("code") != 0:
            raise FeishuError(
                f"{action} 失败（code={body.get('code')}）：{body.get('msg')}。"
                f"若提示无权限，请确认：① 应用已开通多维表格读写权限并发布；"
                f"② 已在多维表格右上角「...」→「更多」→「添加文档应用」里添加本应用。"
            )
        return body.get("data") or {}

    # ---- 多维表格 ----

    def list_records(self, table_id: str) -> list[dict]:
        """列出一个表的全部记录，自动翻页。返回 [{record_id, fields}, ...]"""
        items: list[dict] = []
        page_token: str | None = None
        while True:
            params: dict = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{API_BASE}/bitable/v1/apps/{self.base_token}"
                f"/tables/{table_id}/records",
                headers=self._headers(), params=params, timeout=TIMEOUT,
            ).json()
            data = self._check(resp, "读取记录")
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                return items
            page_token = data.get("page_token")

    def create_record(self, table_id: str, fields: dict) -> str:
        resp = requests.post(
            f"{API_BASE}/bitable/v1/apps/{self.base_token}"
            f"/tables/{table_id}/records",
            headers=self._headers(), json={"fields": fields}, timeout=TIMEOUT,
        ).json()
        data = self._check(resp, "新建记录")
        return data["record"]["record_id"]

    def update_record(self, table_id: str, record_id: str, fields: dict) -> None:
        resp = requests.put(
            f"{API_BASE}/bitable/v1/apps/{self.base_token}"
            f"/tables/{table_id}/records/{record_id}",
            headers=self._headers(), json={"fields": fields}, timeout=TIMEOUT,
        ).json()
        self._check(resp, "更新记录")

    def list_field_names(self, table_id: str) -> dict[str, int]:
        """返回 {字段名: 字段类型码}，供 setup_check 校验表结构。"""
        resp = requests.get(
            f"{API_BASE}/bitable/v1/apps/{self.base_token}"
            f"/tables/{table_id}/fields",
            headers=self._headers(), params={"page_size": 100}, timeout=TIMEOUT,
        ).json()
        data = self._check(resp, "读取字段列表")
        return {item["field_name"]: item["type"] for item in data.get("items") or []}
