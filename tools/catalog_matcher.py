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

ORGANIZATION_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "limited",
    "llc",
    "ltd",
    "srl",
}

ORGANIZATION_QUALIFIERS = {
    "us",
}


def normalized_words(value: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def normalized_identity(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def normalized_organization(value: str) -> str:
    words = normalized_identity(value).split()
    while words and words[-1] in ORGANIZATION_SUFFIXES:
        words.pop()
    while words and words[-1] in ORGANIZATION_QUALIFIERS:
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
        normalized_organization(value)
        for value in game.get("developers", [])
        if normalized_organization(value)
    }
    canonical_publishers = {
        normalized_organization(value)
        for value in game.get("publishers", [])
        if normalized_organization(value)
    }
    product_developer = normalized_organization(offer["developer"])
    developer_matches = bool(
        product_developer and product_developer in canonical_developers
    )
    publisher_matches = bool(
        product_developer and product_developer in canonical_publishers
    )
    if developer_matches:
        reasons.append("Developer matches the canonical game")
    elif publisher_matches:
        reasons.append("Official publisher matches the canonical game")
    elif (canonical_developers or canonical_publishers) and product_developer:
        reasons.append("Developer or publisher differs from the canonical game")
        rejected = True
    else:
        reasons.append("Developer and publisher information is incomplete")

    if rejected or not title_source:
        status = "Rejected"
    elif title_source and (developer_matches or publisher_matches):
        status = "ApprovedCandidate"
    else:
        status = "NeedsReview"
    return {
        "status": status,
        "reasons": reasons,
        "titleMatchSource": title_source,
        "developerMatched": developer_matches,
        "publisherMatched": publisher_matches,
    }
