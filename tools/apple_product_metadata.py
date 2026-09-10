"""Shared Apple App Store product classification helpers."""

from __future__ import annotations


APPLE_GAMES_GENRE_ID = "6014"
APPLE_GAMES_GENRE_NAMES = {"games", "게임"}


def is_game(product: dict) -> bool:
    primary_genre_id = str(product.get("primaryGenreId", ""))
    genre_ids = {str(value) for value in product.get("genreIds", [])}
    primary_genre = str(product.get("primaryGenreName", "")).casefold()
    genres = {str(value).casefold() for value in product.get("genres", [])}
    return (
        primary_genre_id == APPLE_GAMES_GENRE_ID
        or APPLE_GAMES_GENRE_ID in genre_ids
        or primary_genre in APPLE_GAMES_GENRE_NAMES
        or bool(genres & APPLE_GAMES_GENRE_NAMES)
    )
