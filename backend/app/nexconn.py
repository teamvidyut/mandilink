"""Nexconn Server API client.

Signing follows the official Nexconn server SDKs:
    headers: App-Key, Nonce, Timestamp (ms), Signature = sha1(AppSecret + Nonce + Timestamp)
Endpoints used (from the official OpenAPI spec in NexconnAI-Dev/nexconn-server-sdk-go):
    POST /v4/auth/access-token/issue      register user + get access token
    POST /v4/user/update                  update name / avatar
    POST /v4/direct-channel/message/send  bot -> user direct message
    POST /v4/group-channel/create         deal rooms / support rooms / mandi rooms
    POST /v4/group-channel/join           add members (buyer, seller, agent)
    POST /v4/group-channel/message/send   bot / system posts into a group

When no App Key / Secret is configured the client runs in DEMO MODE: the same
calls are served by the in-process DevHub so the full app works locally without
credentials. Demo mode is clearly flagged in the UI and must never be used for
the hackathon submission.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("mandilink.nexconn")

# Built-in text type plus MandiLink custom message types (registered on the client
# with NCEngine.registerCustomMessages). Custom types must not start with "RC:".
TEXT = "RC:TxtMsg"
MSG_LISTING = "ML:Listing"
MSG_DEAL = "ML:Deal"
MSG_NOTICE = "ML:Notice"
MSG_VOICE = "ML:Voice"

DIRECT = 1
GROUP = 3


class NexconnError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"Nexconn error {code}: {message}")
        self.code = code


def sign(app_secret: str, nonce: str, timestamp: str) -> str:
    return hashlib.sha1((app_secret + nonce + timestamp).encode()).hexdigest()


def text_content(text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wire format of RC:TxtMsg (the client SDK maps `text` <-> `content`)."""
    body: dict[str, Any] = {"content": text}
    if extra:
        body["extra"] = json.dumps(extra, ensure_ascii=False)
    return body


class NexconnClient:
    def __init__(self) -> None:
        self.s = get_settings()
        self._hosts = [h for h in [self.s.nexconn_api_host, self.s.nexconn_backup_api_host] if h]
        self._host_idx = 0
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ infra
    @property
    def demo_mode(self) -> bool:
        return not self.s.nexconn_enabled

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(max(1, len(self._hosts))):
            host = self._hosts[self._host_idx % len(self._hosts)]
            nonce = str(secrets.randbelow(10**12))
            ts = str(int(time.time() * 1000))
            headers = {
                "App-Key": self.s.nexconn_app_key,
                "Nonce": nonce,
                "Timestamp": ts,
                "Signature": sign(self.s.nexconn_app_secret, nonce, ts),
                "X-Request-ID": secrets.token_hex(12),
                "Content-Type": "application/json",
            }
            try:
                client = await self._client()
                resp = await client.post(host.rstrip("/") + path, headers=headers, json=body)
            except httpx.HTTPError as exc:  # network failure -> try backup host
                last_exc = exc
                self._host_idx += 1
                log.warning("Nexconn host %s failed (%s), attempt %s", host, exc, attempt + 1)
                continue
            if resp.status_code >= 500 and len(self._hosts) > 1:
                self._host_idx += 1
                last_exc = NexconnError(resp.status_code, resp.text[:200])
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                raise NexconnError(resp.status_code, resp.text[:200]) from exc
            code = int(data.get("code", resp.status_code))
            if code not in (0, 200):
                raise NexconnError(code, data.get("msg") or data.get("errorMessage") or json.dumps(data)[:200])
            return data
        raise NexconnError(-1, f"All Nexconn hosts failed: {last_exc}")

    # -------------------------------------------------------------- user APIs
    async def issue_token(self, user_id: str, name: str, avatar_url: str = "") -> str:
        if self.demo_mode:
            return f"demo-{user_id}"
        body: dict[str, Any] = {"userId": user_id, "name": name}
        if avatar_url:
            body["avatarUrl"] = avatar_url
        data = await self._post("/v4/auth/access-token/issue", body)
        token = (data.get("result") or {}).get("accessToken") or data.get("token")
        if not token:
            raise NexconnError(-2, "No accessToken in response")
        return token

    async def update_user(self, user_id: str, name: str, avatar_url: str = "") -> None:
        if self.demo_mode:
            return
        body: dict[str, Any] = {"userId": user_id, "name": name}
        if avatar_url:
            body["avatarUrl"] = avatar_url
        await self._post("/v4/user/update", body)

    # ------------------------------------------------------------- group APIs
    async def create_group(self, channel_id: str, name: str, owner: str, members: list[str]) -> None:
        if self.demo_mode:
            from .devhub import hub

            hub.add_members(channel_id, [owner, *members])
            return
        await self._post(
            "/v4/group-channel/create",
            {"channelId": channel_id, "name": name, "owner": owner, "userIds": members[:30]},
        )

    async def join_group(self, channel_id: str, user_ids: list[str]) -> None:
        if self.demo_mode:
            from .devhub import hub

            hub.add_members(channel_id, user_ids)
            return
        await self._post("/v4/group-channel/join", {"channelId": channel_id, "userIds": user_ids})

    # ----------------------------------------------------------- message APIs
    async def send_direct(
        self,
        from_user: str,
        to_users: list[str],
        message_type: str,
        content: dict[str, Any],
        push_content: str = "",
    ) -> None:
        if self.demo_mode:
            from .devhub import hub

            for uid in to_users:
                await hub.publish(DIRECT, uid, from_user, message_type, content)
            return
        body: dict[str, Any] = {
            "fromUserId": from_user,
            "toUserIds": to_users,
            "messageType": message_type,
            "content": json.dumps(content, ensure_ascii=False),
            "isEchoToSender": 0,
        }
        if push_content:
            body["pushContent"] = push_content[:200]
        await self._post("/v4/direct-channel/message/send", body)

    async def send_group(
        self,
        from_user: str,
        channel_id: str,
        message_type: str,
        content: dict[str, Any],
        push_content: str = "",
    ) -> None:
        if self.demo_mode:
            from .devhub import hub

            await hub.publish(GROUP, channel_id, from_user, message_type, content)
            return
        body: dict[str, Any] = {
            "fromUserId": from_user,
            "toChannelIds": [channel_id],
            "messageType": message_type,
            "content": json.dumps(content, ensure_ascii=False),
            "isEchoToSender": 0,
        }
        if push_content:
            body["pushContent"] = push_content[:200]
        await self._post("/v4/group-channel/message/send", body)


nexconn = NexconnClient()
