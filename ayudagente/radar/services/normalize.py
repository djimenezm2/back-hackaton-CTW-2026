"""
Mapping raw Apify payloads onto `Observation` and `Media` fields.

Every platform names the same thing differently, and several of them omit fields the others
provide, so the mapping lives in one place rather than inside whichever caller needs it. Both
the pilot fixture loader and the live harvester go through here, which is also what keeps the
seeded data faithful to what the scraper actually returns.
"""

from datetime import UTC, datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from ayudagente.radar.choices import MediaKind, Platform

# Twitter serializes dates as "Tue Aug 11 14:41:22 +0000 2026"
TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"


def parse_timestamp(value: Any) -> datetime | None:
    """
    Read the several shapes platforms use for a publication time.

    Args:
        value (Any): ISO string, Twitter's own format, or epoch seconds/milliseconds.

    Returns:
        datetime | None: An aware datetime, or None when the value is unusable.
    """
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e11 else value  # Facebook reports milliseconds
        return datetime.fromtimestamp(seconds, tz=UTC)
    parsed = parse_datetime(str(value))
    if parsed:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        return datetime.strptime(str(value), TWITTER_DATE_FORMAT)
    except ValueError:
        return None


def _get(item: dict, path: str, default: Any = None) -> Any:
    """Read a dotted path, treating a list as its first element."""
    current: Any = item
    for key in path.split("."):
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _normalize_x(item: dict) -> tuple[dict, list[dict]]:
    """
    Map a tweet.

    Note:
        X is the only platform that gives a thread id, which is what lets a whole
        conversation be pulled later. Its `place` field arrives on about 2% of tweets, so
        the location almost always has to come out of the text instead.
    """
    media = [
        {
            "kind": MediaKind.VIDEO
            if m.get("type") in {"video", "animated_gif"}
            else MediaKind.IMAGE,
            "source_url": m.get("media_url_https", ""),
            "platform_alt_text": _get(m, "additional_media_info.description", "") or "",
            "position": index,
        }
        for index, m in enumerate(_get(item, "extendedEntities.media", []) or [])
        if isinstance(m, dict) and m.get("media_url_https")
    ]
    fields = {
        "platform_id": str(item.get("id", "")),
        "permalink": item.get("url") or item.get("twitterUrl", ""),
        "text": item.get("text", "") or "",
        "language": item.get("lang", "") or "",
        "author_handle": _get(item, "author.userName", "") or "",
        "author_name": _get(item, "author.name", "") or "",
        "author_platform_id": str(_get(item, "author.id", "") or ""),
        "author_avatar_url": _get(item, "author.profilePicture", "") or "",
        "author_followers": _get(item, "author.followers"),
        "author_verified": _get(item, "author.isVerified"),
        "author_bio": _get(item, "author.description", "") or "",
        "platform_geo_name": _get(item, "place.full_name", "") or "",
        "thread_id": str(item.get("conversationId", "") or ""),
        "reply_to_id": str(item.get("inReplyToId", "") or ""),
        "is_reply": bool(item.get("isReply")),
        "hashtags": [
            h["text"] for h in item.get("entities", {}).get("hashtags", []) if h.get("text")
        ],
        "mentions": [
            m["screen_name"]
            for m in item.get("entities", {}).get("user_mentions", [])
            if m.get("screen_name")
        ],
        "external_links": [
            u["expanded_url"]
            for u in item.get("entities", {}).get("urls", [])
            if u.get("expanded_url")
        ],
        "metrics": {
            "likes": item.get("likeCount", 0),
            "shares": item.get("retweetCount", 0),
            "comments": item.get("replyCount", 0),
            "views": item.get("viewCount", 0),
        },
        "posted_at": parse_timestamp(item.get("createdAt")),
    }
    return fields, media


def _normalize_instagram(item: dict) -> tuple[dict, list[dict]]:
    """
    Map an Instagram post.

    Note:
        A carousel puts its extra images under `childPosts`, so one post routinely yields
        several media rows. Instagram gives no follower count and no avatar, which is why
        credibility has to be scored per platform.
    """
    urls = [
        item.get("displayUrl"),
        *(item.get("images") or []),
        *(child.get("displayUrl") for child in item.get("childPosts") or []),
    ]
    media = [
        {
            "kind": MediaKind.IMAGE,
            "source_url": url,
            "platform_alt_text": item.get("alt") or "" if index == 0 else "",
            "position": index,
        }
        for index, url in enumerate(dict.fromkeys(u for u in urls if u))
    ]
    fields = {
        "platform_id": str(item.get("id") or item.get("shortCode", "")),
        "permalink": item.get("url", ""),
        "text": item.get("caption", "") or "",
        "author_handle": item.get("ownerUsername", "") or "",
        "author_name": item.get("ownerFullName", "") or "",
        "author_platform_id": str(item.get("ownerId", "") or ""),
        "platform_geo_name": item.get("locationName", "") or "",
        "hashtags": list(item.get("hashtags") or []),
        "mentions": list(item.get("mentions") or []),
        "metrics": {
            "likes": item.get("likesCount", 0),
            "comments": item.get("commentsCount", 0),
        },
        "posted_at": parse_timestamp(item.get("timestamp")),
    }
    return fields, media


def _normalize_facebook(item: dict) -> tuple[dict, list[dict]]:
    """
    Map a Facebook post.

    Note:
        `accessibilityCaption` is Facebook's own OCR of the attached image and arrives on
        every post that carries media. It often makes a vision call unnecessary.
    """
    media = [
        {
            "kind": MediaKind.VIDEO if a.get("type") == "video" else MediaKind.IMAGE,
            "source_url": a.get("url", ""),
            # Facebook's own OCR of the image, free on every post that carries media
            "platform_alt_text": a.get("accessibilityCaption", "") or "",
            "position": index,
        }
        for index, a in enumerate(item.get("attachments") or [])
        if isinstance(a, dict) and a.get("url")
    ]
    fields = {
        "platform_id": str(item.get("postId", "")),
        "permalink": item.get("url", ""),
        "text": item.get("postText", "") or "",
        "author_name": _get(item, "author.name", "") or "",
        "author_platform_id": str(_get(item, "author.id", "") or ""),
        "author_avatar_url": _get(item, "author.profilePicture", "") or "",
        "metrics": {
            "likes": item.get("reactionsCount", 0),
            "comments": item.get("commentsCount", 0),
            "shares": item.get("sharesCount", 0),
        },
        "posted_at": parse_timestamp(item.get("timestamp")),
    }
    return fields, media


def _normalize_tiktok(item: dict) -> tuple[dict, list[dict]]:
    """
    Map a TikTok video.

    Note:
        Subtitles carry the spoken narration on about 70% of videos and are the cheapest
        way to read one, but they arrive as signed URLs that have to be fetched separately,
        so `transcript` is left for the harvester to fill.
    """
    media = []
    if _get(item, "videoMeta.coverUrl"):
        media.append(
            {
                "kind": MediaKind.COVER,
                "source_url": _get(item, "videoMeta.coverUrl"),
                "platform_alt_text": "",
                "position": 0,
            }
        )
    fields = {
        "platform_id": str(item.get("id", "")),
        "permalink": item.get("webVideoUrl", ""),
        "text": item.get("text", "") or "",
        "author_handle": _get(item, "authorMeta.name", "") or "",
        "author_name": _get(item, "authorMeta.nickName", "") or "",
        "author_platform_id": str(_get(item, "authorMeta.id", "") or ""),
        "author_avatar_url": _get(item, "authorMeta.avatar", "") or "",
        "author_followers": _get(item, "authorMeta.fans"),
        "author_verified": _get(item, "authorMeta.verified"),
        "author_bio": _get(item, "authorMeta.signature", "") or "",
        "platform_geo_name": _get(item, "locationMeta.locationName", "") or "",
        "hashtags": [h["name"] for h in item.get("hashtags") or [] if h.get("name")],
        "mentions": list(item.get("mentions") or []),
        "metrics": {
            "views": item.get("playCount", 0),
            "likes": item.get("diggCount", 0),
            "shares": item.get("shareCount", 0),
            "comments": item.get("commentCount", 0),
        },
        "posted_at": parse_timestamp(item.get("createTimeISO")),
    }
    return fields, media


def _normalize_tiktok_comment(item: dict) -> tuple[dict, list[dict]]:
    """
    Map a TikTok comment.

    Note:
        A comment has no page of its own, so the video URL plus the comment id stands in as
        the permalink and the video id as the thread.
    """
    video_url = item.get("videoWebUrl", "")
    fields = {
        "platform_id": str(item.get("cid", "")),
        "permalink": f"{video_url}?comment={item.get('cid', '')}" if video_url else "",
        "text": item.get("text", "") or "",
        "author_handle": item.get("uniqueId", "") or "",
        "author_platform_id": str(item.get("uid", "") or ""),
        "thread_id": video_url.rstrip("/").split("/")[-1] if video_url else "",
        "reply_to_id": str(item.get("repliesToId", "") or ""),
        "is_reply": bool(item.get("repliesToId")),
        "metrics": {"likes": item.get("diggCount", 0)},
        "posted_at": parse_timestamp(item.get("createTimeISO")),
    }
    return fields, []


NORMALIZERS = {
    Platform.X: _normalize_x,
    Platform.INSTAGRAM: _normalize_instagram,
    Platform.FACEBOOK: _normalize_facebook,
    Platform.TIKTOK: _normalize_tiktok,
}


def normalize(platform: str, item: dict, *, is_comment: bool = False) -> tuple[dict, list[dict]]:
    """
    Map one raw Apify item onto `Observation` fields and its `Media` rows.

    Args:
        platform (str): A `Platform` value.
        item (dict): The raw payload exactly as the Actor returned it.
        is_comment (bool): True when the item is a comment rather than a post, which
            changes the shape enough to need its own mapping.

    Returns:
        tuple[dict, list[dict]]: Observation field values, and one dict per media item.
            `raw` and `event` are not set here — the caller owns those.

    Raises:
        ValueError: If the platform has no mapping.
    """
    if is_comment:
        if platform != Platform.TIKTOK:
            raise ValueError(f"no comment mapping for platform {platform!r}")
        return _normalize_tiktok_comment(item)
    try:
        return NORMALIZERS[Platform(platform)](item)
    except KeyError as exc:
        raise ValueError(f"no mapping for platform {platform!r}") from exc
