#pragma once

#include "game_price/domain/domain_types.h"

#include <string>
#include <utility>
#include <vector>

namespace game_price {

struct Game {
    Game(
        std::string gameId,
        std::string gameTitle,
        std::string normalizedGameTitle,
        std::vector<Platform> platforms,
        std::vector<std::string> gameGenres = {},
        std::vector<std::string> gameTags = {},
        std::vector<std::string> gameAliases = {},
        std::vector<std::string> normalizedGameAliases = {},
        std::vector<std::string> gameDevelopers = {},
        std::vector<std::string> gamePublishers = {},
        std::string gameImageUrl = {})
        : id(std::move(gameId)),
          title(std::move(gameTitle)),
          normalizedTitle(std::move(normalizedGameTitle)),
          supportedPlatforms(std::move(platforms)),
          genres(std::move(gameGenres)),
          tags(std::move(gameTags)),
          aliases(std::move(gameAliases)),
          normalizedAliases(std::move(normalizedGameAliases)),
          developers(std::move(gameDevelopers)),
          publishers(std::move(gamePublishers)),
          imageUrl(std::move(gameImageUrl)) {}

    std::string id;
    std::string title;
    std::string normalizedTitle;
    std::vector<Platform> supportedPlatforms;
    std::vector<std::string> genres;
    std::vector<std::string> tags;
    std::vector<std::string> aliases;
    std::vector<std::string> normalizedAliases;
    std::vector<std::string> developers;
    std::vector<std::string> publishers;
    std::string imageUrl;
};

}  // namespace game_price
