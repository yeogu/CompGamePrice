"""Shared conservative Store offer to canonical Game identity matching."""

from __future__ import annotations

import re


EXCLUDED_TITLE_WORDS = {
    "guide",
    "walkthrough",
    "wallpaper",
    "soundtrack",
    "demo",
    "companion",
    "가이드",
    "공략",
    "데모",
    "사운드트랙",
}

DEVELOPER_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "limited",
    "llc",
    "ltd",
}


def normalized_words(value: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def normalized_identity(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def normalized_developer(value: str) -> str:
    words = normalized_identity(value).split()
    while words and words[-1] in DEVELOPER_SUFFIXES:
        words.pop()
    return " ".join(words)


def evaluate(game: dict, offer: dict) -> dict:
    reasons = []
    rejected = False
    if not offer["isGame"]:
        reasons.append("Store category is not a game")
        rejected = True
    if not offer["supportsTargetPlatform"]:
        reasons.append("Product does not support the target platform")
        rejected = True
    if offer["currency"] != "KRW" or offer["priceMinor"] <= 0:
        reasons.append("Product is not a paid KRW purchase")
        rejected = True
    if offer["excludedWords"]:
        reasons.append("Title indicates guide, demo, companion, or media content")
        rejected = True

    product_title = normalized_identity(offer["title"])
    canonical_titles = [game.get("title", ""), *game.get("aliases", [])]
    title_source = next(
        (
            title
            for title in canonical_titles
            if normalized_identity(title)
            and normalized_identity(title) in product_title
        ),
        "",
    )
    if title_source:
        reasons.append(f'Title matches "{title_source}"')
    else:
        reasons.append("Title does not match the canonical title or aliases")

    canonical_developers = {
        normalized_developer(value)
        for value in game.get("developers", [])
        if normalized_developer(value)
    }
    product_developer = normalized_developer(offer["developer"])
    developer_matches = bool(
        product_developer and product_developer in canonical_developers
    )
    if developer_matches:
        reasons.append("Developer matches the canonical game")
    elif canonical_developers and product_developer:
        reasons.append("Developer differs from the canonical game")
        rejected = True
    else:
        reasons.append("Developer information is incomplete")

    if rejected or not title_source:
        status = "Rejected"
    elif title_source and developer_matches:
        status = "ApprovedCandidate"
    else:
        status = "NeedsReview"
    return {
        "status": status,
        "reasons": reasons,
        "titleMatchSource": title_source,
        "developerMatched": developer_matches,
    }
